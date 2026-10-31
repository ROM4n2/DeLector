package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ROM4n2/DeLector/agent/internal/companion"
	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
	"github.com/sashabaranov/go-openai"
	"github.com/spf13/cobra"
)

const (
	defaultAgentPort          = 8002
	defaultAgentPythonURL     = "http://127.0.0.1:8000"
	defaultAgentBaseURL       = "https://api.deepseek.com"
	defaultAgentModel         = "deepseek-flash"
	defaultAgentFallbackURL   = "http://127.0.0.1:11434/v1"
	defaultAgentFallbackModel = "qwen3.5:4b"
)

func newAgentCmd() *cobra.Command {
	var (
		port            int
		pythonURL       string
		baseURL         string
		model           string
		reasoningEffort string
		fallbackURL     string
		fallbackModel   string
	)

	cmd := &cobra.Command{
		Use:   "agent",
		Short: "启动纯 Go 伴学 Agent HTTP SSE 交互常驻服务（挂载原生 Tool Calling 与流式推送）",
		RunE: func(cmd *cobra.Command, _ []string) error {
			key := os.Getenv("DEEPSEEK_API_KEY")
			if key == "" {
				cmd.PrintErrln("[WARN] DEEPSEEK_API_KEY 环境变量未配置，伴学 Agent 调用真实模型将报错")
			}

			if baseURL == defaultAgentBaseURL && os.Getenv("API_BASE_URL") != "" {
				baseURL = os.Getenv("API_BASE_URL")
			}
			if (model == defaultAgentModel || model == "deepseek-chat") && os.Getenv("API_MODEL") != "" {
				model = os.Getenv("API_MODEL")
			}
			if pythonURL == defaultAgentPythonURL && os.Getenv("DELECTOR_PYTHON_URL") != "" {
				pythonURL = os.Getenv("DELECTOR_PYTHON_URL")
			}

			if reasoningEffort == "" && os.Getenv("DELECTOR_REASONING_EFFORT") != "" {
				reasoningEffort = os.Getenv("DELECTOR_REASONING_EFFORT")
			}
			if reasoningEffort == "" && os.Getenv("REASONING_EFFORT") != "" {
				reasoningEffort = os.Getenv("REASONING_EFFORT")
			}

			cfg := openai.DefaultConfig(key)
			if baseURL != "" {
				cfg.BaseURL = baseURL
			}
			client := openai.NewClientWithConfig(cfg)

			pyClient := pythonsvc.NewClient(pythonURL, nil)
			agent := companion.NewCompanionAgent(client, pyClient, model)

			if fallbackURL != "" {
				fbCfg := openai.DefaultConfig("ollama-local")
				fbCfg.BaseURL = fallbackURL
				fbClient := openai.NewClientWithConfig(fbCfg)
				agent.WithFallback(fbClient, fallbackModel)
				cmd.Printf("[delector] Mounted fallback model %s at %s\n", fallbackModel, fallbackURL)
			}

			handler := companion.NewHandler(agent)

			addr := fmt.Sprintf("127.0.0.1:%d", port)
			server := &http.Server{
				Addr:         addr,
				Handler:      handler,
				ReadTimeout:  60 * time.Second,
				WriteTimeout: 120 * time.Second,
			}

			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()

			serverErr := make(chan error, 1)
			go func() {
				cmd.Printf("[delector] Companion Agent serving at http://%s (Python: %s)\n", addr, pythonURL)
				if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
					serverErr <- err
				}
				close(serverErr)
			}()

			select {
			case err := <-serverErr:
				return fmt.Errorf("companion server error: %w", err)
			case <-ctx.Done():
				cmd.Println("[delector] Shutting down Companion Agent server...")
				shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				return server.Shutdown(shutdownCtx)
			}
		},
	}

	cmd.Flags().IntVar(&port, "port", defaultAgentPort, "伴学 SSE 服务监听端口（默认 8002）")
	cmd.Flags().StringVar(&pythonURL, "python-url", defaultAgentPythonURL, "Python NLP 微服务地址（默认 http://127.0.0.1:8001）")
	cmd.Flags().StringVar(&baseURL, "base-url", defaultAgentBaseURL, "OpenAI/DeepSeek API 根地址")
	cmd.Flags().StringVar(&model, "model", defaultAgentModel, "对话模型名称（默认 deepseek-chat）")
	cmd.Flags().StringVar(&reasoningEffort, "reasoning-effort", "", "思考强度档位（low / medium / high）")
	cmd.Flags().StringVar(&fallbackURL, "fallback-url", defaultAgentFallbackURL, "备用模型（如本地 Ollama）API 根地址")
	cmd.Flags().StringVar(&fallbackModel, "fallback-model", defaultAgentFallbackModel, "备用模型名称（默认 qwen3.5:4b）")

	return cmd
}
