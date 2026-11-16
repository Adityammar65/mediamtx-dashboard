package main

import (
	"encoding/json"
	"net/http"
	"os/exec"
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

	// queryCmd := map[string]string{
	// 	"stop":"sudo systemctl stop mediamtx && killall -9 ffmpeg 2>/dev/null",
	// 	"start":"sudo systemctl start mediamtx && sleep 6",
	// 	"restart":"sudo systemctl stop mediamtx && killall -9 ffmpeg 2>/dev/null; sudo systemctl start mediamtx && sleep 6",
	// }

	queryCmd := map[string]string{
		"stop":"sudo systemctl status mediamtx",
		"start":"sudo systemctl status mediamtx",
		"restart":"sudo systemctl status mediamtx",
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

	cmd := exec.Command("journalctl", "-u", "mediamtx", "-n", lines, "--no-pager")
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
