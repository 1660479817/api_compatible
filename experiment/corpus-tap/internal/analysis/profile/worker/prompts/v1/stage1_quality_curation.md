# Stage 1: Interaction Quality & Curation

You are an expert data curator and linguist. Your task is to evaluate a conversation between a User and an AI Assistant and extract high-quality assets.

## Conversation to Evaluate
```json
{{.ConversationJSON}}
```

## Evaluation Criteria
- **Tier A**: High-quality, meaningful interaction. Evidence of complex problem-solving, creative writing, detailed explanation, or high-value information exchange. Suitable for RAG and SFT.
- **Tier B**: Common interaction, simple Q&A, or informational but not particularly "golden". Useful for basic stats but not primary training/RAG.
- **Tier C**: Low quality, "hello/test" messages, model errors, repetition, or meaningless content. Should be discarded.

## Tasks
1. Assign a `tier` (A, B, or C).
2. Assign a `quality_score` (0.0 to 1.0).
3. If Tier A:
   - Provide a `curated_chunk`: a cleaned-up version of the most valuable part of the interaction for a vector database. Include a `title`.
   - Provide an `sft_candidate`: if the assistant's response is a good example of how it should behave, provide an `instruction` and `output` pair.

## Output Format
Respond ONLY with a JSON object:
```json
{
  "tier": "A|B|C",
  "quality_score": 0.95,
  "rag_indexable": true,
  "curated_chunk": {
    "title": "...",
    "text": "..."
  },
  "sft_candidate": {
    "instruction": "...",
    "output": "...",
    "eligible": true
  },
  "evidence": "Brief reason for this rating"
}
```
