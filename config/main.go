package main

import (
	"bufio"
	"bytes"
	"log"
	"strings"
	"encoding/json"
	"net/http"
	"os/exec"
	"os"
	"fmt"
	"time"
)

type Response struct {
	Status string `json:"status"`
	Message string `json:"message"`
	Data string `json:"data"`
}

var ignoredInfPatterns = []string{
	"frame=",
	"built with gcc",
	"--",
	"ffmpeg",
	"libav",
	"libsw",
	"libpostproc",
	"speed=",
}

type AgentLogPayload struct {
	Timestamp string `json:"timestamp,omitempty"`
	Level     string `json:"level,omitempty"`
	Message   string `json:"message"`
	Source    string `json:"source,omitempty"`
}

var dashboardHTTPClient = &http.Client{
	Timeout: 5 * time.Second,
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

func logService(w http.ResponseWriter, r *http.Request) {
	lines := r.URL.Query().Get("lines")
	if lines == "" {
		lines = "50"
	}

	args := []string{"-u", "mediamtx", "-n", lines, "--no-pager"}
	date := r.URL.Query().Get("date")
	if date != "" {
		if _, err := time.Parse("2006-01-02", date); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]string{"logs": "Format tanggal harus YYYY-MM-DD"})
			return
		}
		args = append(args, "--since", date+" 00:00:00", "--until", date+" 23:59:59")
	}

	cmd := exec.Command("journalctl", args...)
	output, err := cmd.Output()

	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]string{"logs": "Gagal membaca log: " + err.Error()})
		return
	}

	json.NewEncoder(w).Encode(map[string]string{"logs": string(output)})
}

func isIgnoredInfLine(line string) bool {
	lower := strings.ToLower(line)
	for _, pat := range ignoredInfPatterns {
		if strings.Contains(lower, strings.ToLower(pat)) {
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

	url := "http://172.16.18.210:8000/api/logs/agent-events"

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
	http.ListenAndServe(":8081", nil)
}
