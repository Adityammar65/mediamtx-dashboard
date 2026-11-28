package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

type Response struct {
	Status  string `json:"status"`
	Message string `json:"message"`
	Data    string `json:"data"`
}

var ignoredInfPatterns = []string{
	"frame=",
	"fps=",
	"bitrate=",
	"size=n/a",
	"built with gcc",
	"ffmpeg",
	"libav",
	"libsw",
	"libpostproc",
	"conn ",
	"session ",
	"muxer ",
	"is available and online",
}

type AgentLogPayload struct {
	Timestamp string `json:"timestamp,omitempty"`
	Level     string `json:"level,omitempty"`
	Message   string `json:"message"`
	Source    string `json:"source,omitempty"`
}

var dashboardHTTPClient = &http.Client{
	Timeout: 20 * time.Second,
}

func controlService(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not Allowed", http.StatusMethodNotAllowed)
		return
	}

	action := r.URL.Query().Get("action")

	if action != "start" && action != "stop" && action != "restart" {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(Response{Status: "error", Message: "Invalid action", Data: "",})
		return
	}

	queryCmd := map[string]string{
		"stop":"sudo systemctl stop mediamtx && killall -9 ffmpeg 2>/dev/null",
		"start":"sudo systemctl start mediamtx && sleep 6",
		"restart":"sudo systemctl stop mediamtx && killall -9 ffmpeg 2>/dev/null; sudo systemctl start mediamtx && sleep 6",
	}

	cmd := exec.Command("sh", "-c", queryCmd[action])
	err := cmd.Run()

	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(Response{
			Status:  "error",
			Message: "Gagal menjalankan perintah : " + err.Error(),
			Data: "Query : " + queryCmd[action],
		})
		return
	}

	json.NewEncoder(w).Encode(Response{
		Status: "success",
		Message: "Berhasil mengeksekusi perintah.",
		Data: "Query : " + queryCmd[action],
	})
}

func isFFmpegProgressLine(line string) bool {
	return strings.Contains(line, "frame=") && strings.Contains(line, "fps=")
}

func detectLogLevel(line string) string {
	upper := strings.ToUpper(line)
	padded := " " + upper + " "
	switch {
	case strings.Contains(padded, " ERR ") || strings.Contains(upper, "[ERR]") || strings.Contains(upper, "ERROR"):
		return "ERR"
	case strings.Contains(padded, " WRN ") || strings.Contains(padded, " WAR ") || strings.Contains(upper, "[WRN]") || strings.Contains(upper, "[WAR]") || strings.Contains(upper, "WARN"):
		return "WAR"
	case strings.Contains(padded, " DBG ") || strings.Contains(upper, "[DBG]") || strings.Contains(upper, "DEBUG"):
		return "DEBUG"
	case strings.Contains(padded, " INF ") || strings.Contains(upper, "[INF]"):
		return "INF"
	default:
		return "INF"
	}
}

func parseRequestedLevels(r *http.Request) map[string]bool {
	allowed := make(map[string]bool)
	for _, rawVal := range r.URL.Query()["level"] {
		for _, part := range strings.Split(rawVal, ",") {
			lvl := strings.TrimSpace(strings.ToUpper(part))
			if lvl == "" {
				continue
			}
			if lvl == "WARNING" || lvl == "WRN" {
				lvl = "WAR"
			} else if lvl == "ERROR" {
				lvl = "ERR"
			} else if lvl == "DBG" {
				lvl = "DEBUG"
			}
			allowed[lvl] = true
		}
	}
	return allowed
}

func buildJournalctlArgs(date string, useGrep bool) []string {
	args := []string{"-u", "mediamtx", "--no-pager", "-o", "short"}
	if useGrep {
		// Buang baris progres ffmpeg (frame=... fps=...) langsung di journalctl (PCRE2)
		args = append(args, "--grep", `^(?!.*frame=.*fps=).*`)
	}
	if date != "" {
		args = append(args, "--since", date+" 00:00:00", "--until", date+" 23:59:59")
	}
	return args
}

func runJournalctlFiltered(args []string, allowedLevels map[string]bool, maxLines int) ([]string, error) {
	cmd := exec.Command("journalctl", args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}

	if err := cmd.Start(); err != nil {
		return nil, err
	}

	reader := bufio.NewReader(stdout)
	filtered := make([]string, 0, 256)

	for {
		line, readErr := reader.ReadString('\n')
		trimmed := strings.TrimSpace(line)
		if trimmed != "" && !isFFmpegProgressLine(trimmed) {
			if len(allowedLevels) == 0 || allowedLevels[detectLogLevel(trimmed)] {
				filtered = append(filtered, trimmed)
				if maxLines > 0 && len(filtered) > maxLines {
					// Pertahankan maksimal maxLines baris terakhir agar memori & waktu tetap terjaga
					filtered = filtered[len(filtered)-maxLines:]
				}
			}
		}

		if readErr != nil {
			if readErr == io.EOF {
				break
			}
			_ = cmd.Wait()
			return nil, readErr
		}
	}

	if err := cmd.Wait(); err != nil {
		return nil, err
	}

	return filtered, nil
}

func logService(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	allowedLevels := parseRequestedLevels(r)
	date := strings.TrimSpace(r.URL.Query().Get("date"))

	if date != "" {
		if _, err := time.Parse("2006-01-02", date); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]string{"logs": "Format tanggal harus YYYY-MM-DD"})
			return
		}
	} else {
		linesParam := r.URL.Query().Get("lines")
		if linesParam != "" {
			if parsed, err := strconv.Atoi(linesParam); err != nil || parsed <= 0 {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(map[string]string{"logs": "Parameter lines harus berupa angka positif"})
				return
			}
		}
	}

	// Coba pakai --grep dulu (tanpa batas baris saat date diisi)
	filtered, err := runJournalctlFiltered(buildJournalctlArgs(date, true), allowedLevels, 0)
	if err != nil {
		// Fallback tanpa --grep: pasang batas baris agar tetap cepat
		fallbackMax := 5000
		if date == "" {
			linesParam := r.URL.Query().Get("lines")
			if linesParam != "" {
				if parsed, errParse := strconv.Atoi(linesParam); errParse == nil && parsed > 0 {
					fallbackMax = parsed
				}
			} else {
				fallbackMax = 500
			}
		}
		filtered, err = runJournalctlFiltered(buildJournalctlArgs(date, false), allowedLevels, fallbackMax)
	}
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"logs": "Gagal membaca log: " + err.Error()})
		return
	}

	if date == "" {
		linesParam := r.URL.Query().Get("lines")
		limit := 500
		if linesParam != "" {
			if parsed, err := strconv.Atoi(linesParam); err == nil && parsed > 0 {
				limit = parsed
			}
		}
		if len(filtered) > limit {
			filtered = filtered[len(filtered)-limit:]
		}
	}

	json.NewEncoder(w).Encode(map[string]string{"logs": strings.Join(filtered, "\n")})
}

func isIgnoredInfLine(line string) bool {
	lower := strings.ToLower(line)
	for _, pat := range ignoredInfPatterns {
		if strings.Contains(lower, pat) {
			return true
		}
	}
	return false
}

func sendLogToDashboard(payload AgentLogPayload) error {
	log.Printf("DEBUG: Sending log: %s", payload.Message)
	if payload.Source == "" {
		payload.Source = "mediamtx"
	}
	if payload.Timestamp == "" {
		payload.Timestamp = time.Now().Format(time.RFC3339Nano)
	}

	bodyBytes, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal payload error: %w", err)
	}

	url := os.Getenv("DASHBOARD_MEDIAMTX_URL")
	if url == "" {
		url = "http://172.16.18.210:8000/api/logs/agent-events"
	}

	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("create request error: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if token := os.Getenv("AGENT_LOG_TOKEN"); token != "" {
		req.Header.Set("X-Agent-Token", token)
	}

	resp, err := dashboardHTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("http post error: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

var agentLogQueue = make(chan AgentLogPayload, 200)

func startDashboardLogWorker() {
	go func() {
		for item := range agentLogQueue {
			if err := sendLogToDashboard(item); err != nil {
				log.Printf("failed to send log to dashboard: %v | msg=%s", err, item.Message)
			}
		}
	}()
}

func handleImportantInfLog(line string) {
	payload := AgentLogPayload{
		Timestamp: time.Now().Format(time.RFC3339Nano),
		Level:     "INF",
		Message:   line,
		Source:    "mediamtx",
	}

	select {
	case agentLogQueue <- payload:
	default:
		log.Printf("agentLogQueue full, dropping log: %s", line)
	}
}

func followJournalctlINF(unit string) {
	for {
		cmd := exec.Command("journalctl", "-u", unit, "-f", "--no-pager", "-o", "short")

		stdout, err := cmd.StdoutPipe()
		if err != nil {
			log.Printf("journalctl StdoutPipe error: %v", err)
			time.Sleep(3 * time.Second)
			continue
		}

		if err := cmd.Start(); err != nil {
			log.Printf("journalctl start error: %v", err)
			time.Sleep(3 * time.Second)
			continue
		}

		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}

			if strings.Contains(line, "INF") && !isIgnoredInfLine(line) {
				handleImportantInfLog(line)
			}
		}

		if err := scanner.Err(); err != nil {
			log.Printf("journalctl scanner error: %v", err)
		}

		_ = cmd.Wait()
		log.Printf("journalctl exited, restarting follower in 3s...")
		time.Sleep(3 * time.Second)
	}
}

func main() {
	startDashboardLogWorker()
	go followJournalctlINF("mediamtx")
	http.HandleFunc("/service", controlService)
	http.HandleFunc("/logs", logService)
	log.Println("mediamtx-agent listening on :8081")
	if err := http.ListenAndServe(":8081", nil); err != nil {
		log.Fatalf("HTTP server error: %v", err)
	}
}