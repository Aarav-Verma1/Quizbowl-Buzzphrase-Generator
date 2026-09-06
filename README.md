# Obsidian — Quiz Bowl Buzzword Analyzer

Analyzes quiz bowl questions from QBReader to extract the most important
"buzzwords" (identifying phrases) for a given answer/topic, using TF-IDF
and optional semantic search. Generates AI-powered explanations for each
buzzword via the Gemini API and exports results as Anki flashcards.

## Features
- Live autocomplete against the QBReader database (exact or semantic search)
- TF-IDF-based buzzword extraction with NLP phrase parsing (spaCy)
- Optional semantic search via sentence-transformers embeddings
- AI-generated explanations for each buzzword (Gemini API)
- Export selected buzzwords to Anki-compatible CSV
- Persistent shopping-cart style flashcard builder (localStorage)
