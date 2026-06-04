package canonical

import (
	"context"
	"encoding/json"
	"fmt"
	"unicode/utf8"

	"corpus-tap/internal/analysis/shared"
	"corpus-tap/internal/store"
)

type Parser struct {
	blob store.BlobBackend
}

func NewParser(blob store.BlobBackend) *Parser {
	return &Parser{blob: blob}
}

func (p *Parser) Parse(ctx context.Context, row store.ExchangeRow) (*CanonicalTurn, error) {
	turn := &CanonicalTurn{
		ExchangeID: row.ID,
		UserID:     row.UserID,
		SessionKey: row.SessionKey,
		CreatedAt:  row.CreatedAt,
		Wire:       row.Wire,
		ModelName:  row.ModelName,
	}

	if row.ClientRequestURI == "" {
		return nil, fmt.Errorf("missing client_request_uri")
	}

	reqBytes, err := p.blob.ReadPlaintext(ctx, row.ClientRequestURI)
	if err != nil {
		return nil, fmt.Errorf("read request: %w", err)
	}

	var respBytes []byte
	if row.AssembledStreamURI != "" {
		respBytes, err = p.blob.ReadPlaintext(ctx, row.AssembledStreamURI)
	} else if row.UpstreamResponseURI != "" {
		respBytes, err = p.blob.ReadPlaintext(ctx, row.UpstreamResponseURI)
	}
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}

	switch row.Wire {
	case "openai_chat":
		err = p.parseOpenAIChat(turn, reqBytes, respBytes, row.IsStream)
	case "anthropic_messages":
		err = p.parseAnthropicMessages(turn, reqBytes, respBytes, row.IsStream)
	case "openai_responses":
		err = p.parseOpenAIResponses(turn, reqBytes, respBytes, row.IsStream)
	default:
		return nil, fmt.Errorf("unsupported wire: %s", row.Wire)
	}

	if err != nil {
		return nil, err
	}

	// Calculate character counts
	for _, m := range turn.Messages {
		count := utf8.RuneCountInString(m.Content)
		if m.Role == RoleAssistant {
			turn.AssistantCharCount += count
		} else if m.Role == RoleUser {
			turn.UserCharCount += count
		}
	}

	return turn, nil
}

func (p *Parser) parseOpenAIChat(turn *CanonicalTurn, reqBody, respBody []byte, isStream bool) error {
	var req struct {
		Messages []struct {
			Role    string `json:"role"`
			Content any    `json:"content"` // can be string or array
		} `json:"messages"`
	}
	if err := json.Unmarshal(reqBody, &req); err != nil {
		return err
	}

	for _, m := range req.Messages {
		content := ""
		if s, ok := m.Content.(string); ok {
			content = s
		} else if arr, ok := m.Content.([]any); ok {
			// Handle complex content (e.g., vision) - just extract text for now
			for _, item := range arr {
				if obj, ok := item.(map[string]any); ok {
					if t, ok := obj["type"].(string); ok && t == "text" {
						if txt, ok := obj["text"].(string); ok {
							content += txt
						}
					}
				}
			}
		}
		turn.Messages = append(turn.Messages, CanonicalMessage{
			Role:    Role(m.Role),
			Content: content,
		})
	}

	if isStream {
		turn.Messages = append(turn.Messages, CanonicalMessage{
			Role:    RoleAssistant,
			Content: shared.ExtractAssistantText(respBody),
		})
	} else {
		var resp struct {
			Choices []struct {
				Message struct {
					Role      string     `json:"role"`
					Content   string     `json:"content"`
					ToolCalls []ToolCall `json:"tool_calls"`
				} `json:"message"`
			} `json:"choices"`
		}
		if err := json.Unmarshal(respBody, &resp); err == nil && len(resp.Choices) > 0 {
			msg := resp.Choices[0].Message
			turn.Messages = append(turn.Messages, CanonicalMessage{
				Role:      RoleAssistant,
				Content:   msg.Content,
				ToolCalls: msg.ToolCalls,
			})
		}
	}
	return nil
}

func (p *Parser) parseAnthropicMessages(turn *CanonicalTurn, reqBody, respBody []byte, isStream bool) error {
	var req struct {
		System   string `json:"system"`
		Messages []struct {
			Role    string `json:"role"`
			Content any    `json:"content"` // can be string or array
		} `json:"messages"`
	}
	if err := json.Unmarshal(reqBody, &req); err != nil {
		return err
	}

	if req.System != "" {
		turn.Messages = append(turn.Messages, CanonicalMessage{Role: RoleSystem, Content: req.System})
	}

	for _, m := range req.Messages {
		content := ""
		if s, ok := m.Content.(string); ok {
			content = s
		} else if arr, ok := m.Content.([]any); ok {
			for _, item := range arr {
				if obj, ok := item.(map[string]any); ok {
					if t, ok := obj["type"].(string); ok && t == "text" {
						if txt, ok := obj["text"].(string); ok {
							content += txt
						}
					}
				}
			}
		}
		turn.Messages = append(turn.Messages, CanonicalMessage{
			Role:    Role(m.Role),
			Content: content,
		})
	}

	if isStream {
		turn.Messages = append(turn.Messages, CanonicalMessage{
			Role:    RoleAssistant,
			Content: string(respBody),
		})
	} else {
		var resp struct {
			Content []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			} `json:"content"`
		}
		if err := json.Unmarshal(respBody, &resp); err == nil {
			content := ""
			for _, c := range resp.Content {
				if c.Type == "text" {
					content += c.Text
				}
			}
			turn.Messages = append(turn.Messages, CanonicalMessage{
				Role:    RoleAssistant,
				Content: content,
			})
		}
	}
	return nil
}

func (p *Parser) parseOpenAIResponses(turn *CanonicalTurn, reqBody, respBody []byte, isStream bool) error {
	// Minimal implementation for OpenAI Responses (Realtime/O1 etc)
	// Similar to chat for many cases
	return p.parseOpenAIChat(turn, reqBody, respBody, isStream)
}
