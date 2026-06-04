package shared

import (
	"encoding/json"
	"strings"
)

// ExtractAssistantText turns Tap's assembled_stream payload (raw SSE bytes) into plain text.
// Tap stores the tee-captured stream as-is; analysis strategies must normalize before LLM.
func ExtractAssistantText(raw []byte) string {
	text := extractFromSSELines(raw)
	if text != "" {
		return text
	}
	return strings.TrimSpace(string(raw))
}

func extractFromSSELines(raw []byte) string {
	var sb strings.Builder
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, ":") {
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if payload == "" || payload == "[DONE]" {
			continue
		}
		if appendOpenAIDelta(&sb, payload) {
			continue
		}
		appendAnthropicDelta(&sb, payload)
	}
	return strings.TrimSpace(sb.String())
}

func appendOpenAIDelta(sb *strings.Builder, payload string) bool {
	var chunk struct {
		Choices []struct {
			Delta struct {
				Content string `json:"content"`
			} `json:"delta"`
			Text string `json:"text"`
		} `json:"choices"`
	}
	if err := json.Unmarshal([]byte(payload), &chunk); err != nil {
		return false
	}
	for _, c := range chunk.Choices {
		if c.Delta.Content != "" {
			sb.WriteString(c.Delta.Content)
		}
		if c.Text != "" {
			sb.WriteString(c.Text)
		}
	}
	return len(chunk.Choices) > 0
}

func appendAnthropicDelta(sb *strings.Builder, payload string) {
	var ev struct {
		Type  string `json:"type"`
		Delta struct {
			Text string `json:"text"`
		} `json:"delta"`
	}
	if err := json.Unmarshal([]byte(payload), &ev); err != nil {
		return
	}
	switch ev.Type {
	case "content_block_delta", "message_delta":
		if ev.Delta.Text != "" {
			sb.WriteString(ev.Delta.Text)
		}
	}
}
