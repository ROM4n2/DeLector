package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestAgentCmdFlagParsing(t *testing.T) {
	cmd := newAgentCmd()
	if cmd.Use != "agent" {
		t.Fatalf("expected command use 'agent', got %s", cmd.Use)
	}

	buf := new(bytes.Buffer)
	cmd.SetOut(buf)
	cmd.SetErr(buf)
	cmd.SetArgs([]string{"--help"})

	if err := cmd.Execute(); err != nil {
		t.Fatalf("help failed: %v", err)
	}

	helpText := buf.String()
	if !strings.Contains(helpText, "--port") {
		t.Errorf("missing --port flag in help: %s", helpText)
	}
	if !strings.Contains(helpText, "--python-url") {
		t.Errorf("missing --python-url flag in help: %s", helpText)
	}
	if !strings.Contains(helpText, "--model") {
		t.Errorf("missing --model flag in help: %s", helpText)
	}
}
