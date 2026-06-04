package shared

import "testing"

func TestExtractAssistantTextOpenAI(t *testing.T) {
	raw := []byte("data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"}}]}\n\n" +
		"data: {\"choices\":[{\"delta\":{\"content\":\" world\"}}]}\n\n" +
		"data: [DONE]\n\n")
	got := ExtractAssistantText(raw)
	if got != "Hello world" {
		t.Fatalf("got %q", got)
	}
}
