package companion

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// ServerHandler 封装伴学 HTTP SSE 服务的路由。
type ServerHandler struct {
	agent *CompanionAgent
	mux   *http.ServeMux
}

// NewHandler 构建满足 /api/companion/chat 与 /api/companion/health 的 HTTP Handler。
func NewHandler(agent *CompanionAgent) http.Handler {
	sh := &ServerHandler{
		agent: agent,
		mux:   http.NewServeMux(),
	}
	sh.mux.HandleFunc("/api/companion/health", sh.handleHealth)
	sh.mux.HandleFunc("/api/companion/chat", sh.handleChat)
	return sh
}

func (sh *ServerHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	sh.mux.ServeHTTP(w, r)
}

func (sh *ServerHandler) handleHealth(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"status":  "ok",
		"service": "delector-go-companion-agent",
	})
}

func (sh *ServerHandler) handleChat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		return
	}

	var req Request
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf("Invalid JSON body: %v", err), http.StatusBadRequest)
		return
	}

	if req.APIKey == "" {
		req.APIKey = r.Header.Get("X-API-Key")
	}
	if req.BaseURL == "" {
		req.BaseURL = r.Header.Get("X-Base-URL")
	}
	if req.Model == "" {
		req.Model = r.Header.Get("X-Model")
	}
	if req.ReasoningEffort == "" {
		req.ReasoningEffort = r.Header.Get("X-Reasoning-Effort")
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming unsupported", http.StatusInternalServerError)
		return
	}

	// 注入标准 SSE 响应头
	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	flusher.Flush()

	emit := func(ev Event) error {
		dataBytes, err := json.Marshal(ev)
		if err != nil {
			return err
		}
		// 遵循 SSE 标准：event: <type>\ndata: <json>\n\n
		_, writeErr := fmt.Fprintf(w, "event: %s\ndata: %s\n\n", ev.Event, string(dataBytes))
		if writeErr == nil {
			flusher.Flush()
		}
		return writeErr
	}

	// 执行伴学 Agent 循环
	_, _ = sh.agent.RunLoop(r.Context(), req, emit)
}
