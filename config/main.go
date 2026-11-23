package main

import (
	"encoding/json"
	"net/http"
	"os/exec"
	"time"
)

type Response struct {
	Status string `json:"status"`
	Message string `json:"message"`
	Data string `json:"data"`
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

func main() {
	http.HandleFunc("/service", controlService)
	http.HandleFunc("/logs", logService)
	http.ListenAndServe(":8081", nil)
}