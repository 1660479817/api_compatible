package canonical

import (
	"time"

	"github.com/google/uuid"
)

// Role defines the participant in the conversation.
type Role string

const (
	RoleSystem    Role = "system"
	RoleUser      Role = "user"
	RoleAssistant Role = "assistant"
	RoleTool      Role = "tool"
)

// CanonicalMessage is a single message in the conversation.
type CanonicalMessage struct {
	Role        Role      `json:"role"`
	Content     string    `json:"content"`
	ToolCalls   []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID  string    `json:"tool_call_id,omitempty"` // For tool role
}

// ToolCall represents a model's request to call a tool.
type ToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"` // e.g., "function"
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

// CanonicalTurn represents the entire exchange between client and upstream.
type CanonicalTurn struct {
	ExchangeID   uuid.UUID          `json:"exchange_id"`
	UserID       int                `json:"user_id"`
	SessionKey   string             `json:"session_key"`
	CreatedAt    time.Time          `json:"created_at"`
	Wire         string             `json:"wire"`
	ModelName    string             `json:"model_name"`
	Messages     []CanonicalMessage `json:"messages"`
	UserCharCount int               `json:"user_char_count"`
	AssistantCharCount int          `json:"assistant_char_count"`
}
