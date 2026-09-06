import re
import requests
import time
from typing import List, Dict, Tuple, Optional, Set
import spacy
from spacy.util import compile_infix_regex, compile_suffix_regex
from tqdm import tqdm
from sklearn.feature_extraction.text import TfidfVectorizer
from difflib import SequenceMatcher
from collections import Counter, defaultdict
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

class TFIDFQuizbowlExtractor:
    """Enhanced TF-IDF buzzword extractor for quizbowl questions using QBReader API."""

    def __init__(self):
        """Initialize models and configurations."""
        print("Initializing enhanced models...")
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("Downloading spaCy model 'en_core_web_sm'...")
            from spacy.cli import download # type: ignore
            download("en_core_web_sm")
            self.nlp = spacy.load("en_core_web_sm")

        # Remove apostrophe patterns from infixes
        infixes = [x for x in self.nlp.Defaults.infixes if "'" not in x and "'" not in x] # type: ignore # type: ignore
        infix_re = compile_infix_regex(infixes)

        # Remove apostrophe patterns from suffixes
        suffixes = [x for x in self.nlp.Defaults.suffixes if "'" not in x and "'" not in x] # type: ignore
        suffix_re = compile_suffix_regex(suffixes)

        # Apply both changes
        self.nlp.tokenizer.infix_finditer = infix_re.finditer # type: ignore
        self.nlp.tokenizer.suffix_search = suffix_re.search # type: ignore

        self.base_url = "https://www.qbreader.org/api"
        self.rate_limit_delay = 0.1

        self.phrase_positions = defaultdict(list)

        # Initialize semantic search model
        print("Loading sentence transformer model for semantic search...")
        try:
            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            print("✅ Semantic search model loaded successfully")
        except Exception as e:
            print(f"⚠️ Failed to load semantic search model: {e}")
            self.sentence_model = None

        # Cache for embeddings and semantic search results
        self.answerline_embeddings = {}
        self.embedding_cache = {}

        # Cache of identifier mode by answerline/topic
        self.last_identifier_by_answer = {}

        self.value_indicators = {
            'high_value': ['technique', 'method', 'principle', 'theory', 'concept', 'phenomenon',
                          'movement', 'period', 'style', 'school', 'doctrine', 'philosophy'],
            'medium_value': ['work', 'piece', 'composition', 'painting', 'novel', 'poem', 'play'],
            'contextual': ['early', 'late', 'first', 'major', 'famous', 'notable', 'important']
        }

        # Default hybrid weights: 60% celerity, 40% frequency
        self.hybrid_weights = {
            'celerity': 0.6,
            'frequency': 0.4
        }

    def _fetch_questions_by_answer(self, answer: str, category: str, max_questions: int):
        """Enhanced question fetching with multiple search strategies."""
        all_questions = []

        # Strategy 1: Direct answer search
        try:
            params = {
                'queryString': answer,
                'searchType': 'answer',
                'categories': category,
                'maxReturnLength': max_questions,
                'minYear': '2010',  # Focus on higher quality recent questions
                'maxYear': '2025'
            }
            response = requests.get(f"{self.base_url}/query", params=params, timeout=10)
            time.sleep(self.rate_limit_delay)

            if response.status_code == 200:
                data = response.json()
                questions = data.get('tossups', {}).get('questionArray', [])
                all_questions.extend(questions)
                print(f"Found {len(questions)} questions from direct search.")
        except requests.exceptions.RequestException as e:
            print(f"Error in direct search: {e}")

        if len(answer.split()) > 1:
            for word in answer.split():
                if len(word) > 3:
                    try:
                        params = {
                            'queryString': word,
                            'searchType': 'answer',
                            'categories': category,
                            'maxReturnLength': max_questions // 3,
                            'minYear': '2015',
                            'maxYear': '2025'
                        }
                        response = requests.get(f"{self.base_url}/query", params=params, timeout=10)
                        time.sleep(self.rate_limit_delay)

                        if response.status_code == 200:
                            data = response.json()
                            questions = data.get('tossups', {}).get('questionArray', [])
                            relevant_questions = [q for q in questions if answer.lower() in q.get('answer', '').lower()]
                            all_questions.extend(relevant_questions)
                            print(f"Found {len(relevant_questions)} additional questions from '{word}' search.")
                    except requests.exceptions.RequestException as e:
                        print(f"Error in partial search for '{word}': {e}")

        # Remove duplicates
        seen_questions = set()
        unique_questions = []
        for q in all_questions:
            question_text = q.get('question', '')
            if question_text not in seen_questions:
                seen_questions.add(question_text)
                unique_questions.append(q)

        print(f"Total unique questions: {len(unique_questions)}")
        return unique_questions[:max_questions]

    def _clean_and_normalize_text(self, text: str):
        """Enhanced text cleaning optimized for quizbowl content."""
        text = re.sub(r'<[^>]+>', '', text) # remove HTML tags
        text = re.sub(r'\(\*\)', '', text) # remove power mark (*)
        text = re.sub(r'[*>]+', '', text) # removes * and > (?)
        text = re.sub(r'$$\*$$', '', text) # removes LaTeX markers (?)
        text = re.sub(r'[\"`]', '', text) # removes ` and double quotes
        text = re.sub(r'\[.*?\]|\(["“”](.*?)["“”]\)|$$.*?$$|•|·', '', text) # removes bracketed text, LaTeX, and various dots
        text = re.sub(r"\('(.*?)'\)", '', text)
        text = re.sub(r'["“”‘’]',"'", text) # replaces double quotes with single quotes
        #text = re.sub(r"['‘’](?!s)", '', text) # removes single quotes

        # removes FTP and subsequent giveaway
        text = re.sub(r'\b(for (10|ten) points)\b.*$', '', text, flags=re.IGNORECASE)

        # removes preidentifiers, to be, to have
        text = re.sub(r'\b(this|these|that|those)\s+(is|was|are|were|has|have|had)\b', '', text, flags=re.IGNORECASE)

        #remove articles
        text = re.sub(r'\b(a|an|An|the|The)\b', '', text)
        text = re.sub(r'\. A\b', '. ', text)
        text = re.sub(r' , ', ', ', text)
        text = re.sub(r' \. ', '. ', text)

        text = re.sub(r'\s+', ' ', text) # collapses multi-whitespace into single space
        return text.strip()

    def _extract_phrases(self, text: str):
        """Enhanced phrase extraction with support for longer phrases."""
        cleantext = self._clean_and_normalize_text(text)
        doc = self.nlp(cleantext)

        phrases = set()

        phrases |= self._extract_noun_chunks(doc, cleantext)
        phrases |= self._extract_entities(doc, cleantext)
        phrases |= self._extract_technical_phrases(doc, cleantext)
        phrases |= self._extract_compound_phrases(doc, cleantext)
        phrases |= self._extract_adjectives(doc, cleantext)
        phrases |= self._extract_letters(doc, cleantext)
        phrases |= self._extract_capitalized(doc, cleantext)

        return phrases

    def _extract_noun_chunks(self, doc, text=""):
        """Extract noun chunks."""
        noun_chunk_phrases = set()

        for chunk in doc.noun_chunks:
            phrase = self._normalize_phrase(chunk.text.strip())
            if self._is_valid_phrase(phrase):
                noun_chunk_phrases.add(phrase.lower())

                if text:
                    self._record_position(phrase.lower(), text)

                if len(phrase.split()) > 3:
                    subchunks = self._extract_subphrases(chunk)

                    for subchunk in subchunks:
                        subphrase = self._normalize_phrase(subchunk)
                        if self._is_valid_phrase(subphrase):
                            noun_chunk_phrases.add(subphrase.lower())

                            if text:
                                self._record_position(phrase.lower(), text)

            elif identifying_phrase := self._expunge_identifiers(phrase):
                if self._is_valid_phrase(identifying_phrase):
                    noun_chunk_phrases.add(identifying_phrase.lower())

                    if text:
                        self._record_position(phrase.lower(), text)

        return noun_chunk_phrases

    def _extract_subphrases(self, chunk):
        """Extract meaningful sub-phrases from longer noun chunks."""
        subphrases = set()  # Use set to avoid duplicates

        # Filter tokens: remove stop words, punctuation, and whitespace
        meaningful_tokens = [
            token for token in chunk
            if not token.is_stop
            and not token.is_punct
            and not token.is_space
            and token.text.strip()  # Ensure token has content after stripping
            and len(token.text.strip()) > 1  # Avoid single characters
        ]

        if len(meaningful_tokens) < 2:
            return subphrases

        # Extract contiguous sub-phrases of 2-4 words
        for i in range(len(meaningful_tokens)):
            for j in range(i + 2, min(i + 5, len(meaningful_tokens) + 1)):
                # Create phrase from lemmatized or original text
                phrase_tokens = meaningful_tokens[i:j]
                phrase = ' '.join(token.text for token in phrase_tokens)

                # Clean and validate the phrase
                cleaned_phrase = ' '.join(phrase.split())  # Remove extra whitespace

                if cleaned_phrase and len(cleaned_phrase.split()) >= 2:
                    subphrases.add(cleaned_phrase.lower())  # Normalize case

        return subphrases

    def _extract_entities(self, doc, text=""):
        """Extract phrases contained named entities from doc."""
        entity_phrases = set()

        for ent in doc.ents:
            if ent.label_ in ['PERSON', 'ORG', 'GPE', 'EVENT', 'WORK_OF_ART', 'LAW', 'LANGUAGE', 'NORP']:

                phrase = self._normalize_phrase(ent.text.strip())
                if self._is_valid_phrase(phrase):
                    entity_phrases.add(phrase.lower())

                    if text:
                        self._record_position(phrase.lower(), text)

                    # get contextual phrases from each main entity using helper function
                    context_phrases = self._extract_entity_context(ent, doc)
                    for ctx_phrase in context_phrases:
                        if self._is_valid_phrase(ctx_phrase):
                            entity_phrases.add(ctx_phrase.lower())

                            if text:
                                self._record_position(ctx_phrase.lower(), text)

        return entity_phrases

    def _extract_technical_phrases(self, doc, text=""):
        """Extract technical and academic terminology."""
        technical_phrases = set()

        for i, token in enumerate(doc):
            # Pattern: adjective + noun + noun (e.g., "quantum mechanical system")
            if (token.pos_ == 'ADJ' and
                i + 2 < len(doc) and
                doc[i + 1].pos_ in ['NOUN', 'ADJ'] and
                doc[i + 2].pos_ in ['NOUN', 'PROPN'] and
                not token.is_stop):
                phrase = f"{token.text} {doc[i + 1].text} {doc[i + 2].text}"
                if self._is_valid_phrase(phrase):
                    technical_phrases.add(phrase.lower())

                    if text:
                        self._record_position(phrase.lower(), text)

            # Pattern: noun + preposition + noun (e.g., "theory of relativity")
            if (token.pos_ in ['NOUN', 'PROPN'] and
                i + 2 < len(doc) and
                doc[i + 1].pos_ == 'ADP' and
                doc[i + 2].pos_ in ['NOUN', 'PROPN'] and
                not token.is_stop and
                not doc[i + 2].is_stop):
                phrase = f"{token.text} {doc[i + 1].text} {doc[i + 2].text}"
                if self._is_valid_phrase(phrase):
                    technical_phrases.add(phrase.lower())

                    if text:
                        self._record_position(phrase.lower(), text)

        return technical_phrases

    def _extract_compound_phrases(self, doc, text=""):
        """Extract significant words modifying a word in its tree."""
        compound_phrases = set()

        for token in doc:
            if token.pos_ in ['NOUN', 'PROPN'] and token.dep_ in ['compound', 'amod']:

                phrase_tokens = [token]

                # Look left for modifiers
                for child in token.children:
                    if child.dep_ in ['amod', 'compound', 'nmod'] and child.i < token.i and not child.text.endswith("."):
                        phrase_tokens.insert(0, child)

                # Look right for compound elements
                for child in token.children:
                    if child.dep_ in ['compound'] and child.i > token.i:
                        phrase_tokens.append(child)

                if len(phrase_tokens) > 1:
                    compound_phrase = ' '.join([t.text for t in phrase_tokens])
                    if self._is_valid_phrase(compound_phrase):
                        compound_phrases.add(compound_phrase.lower())

                        if text:
                            self._record_position(compound_phrase.lower(), text)

        return compound_phrases

    def _extract_adjectives(self, doc, text=""):
        """Extract semantically significant adjectives."""
        adjective_phrases = set()
        key_adjectives = []

        for token in doc:
            if token.pos_ == 'ADJ':

                # check if this adjective has a coordinated sibling
                for child in token.children:
                    if child.dep_ == 'conj' and child.pos_ == 'ADJ':
                        key_adjectives.append(token.text)
                        key_adjectives.append(child.text)
                        break

                # check if this adjective is coordinated TO another adjective
                if token.dep_ == 'conj' and token.head.pos_ == 'ADJ':
                    key_adjectives.append(token.text)

                # adjectives not directly modifying nouns
                elif token.dep_ not in ['amod', 'nmod']:  # amod = adjectival modifier
                    key_adjectives.append(token.text)

        for adjective in key_adjectives:
            if self._is_valid_phrase(adjective):
                adjective_phrases.add(adjective.lower())

                if text:
                    self._record_position(adjective.lower(), text)

        return adjective_phrases

    def _extract_letters(self, doc, text=""):
        """Extract phrases consisting of words followed by single letters."""
        letter_phrases = set()

        for i in range(len(doc) - 1):
            word = doc[i]
            letter = doc[i+1]
            letter_text = letter.text

            if len(letter_text) == 2 and letter_text.endswith("."):
                letter_text = letter.text[0]

            if len(letter_text) == 1 and letter_text.isalpha():
                phrase = f"{word.text} {letter_text}".strip().lower()

                if self._is_valid_phrase(phrase):
                    letter_phrases.add(phrase)

                    if text:
                        self._record_position(phrase.lower(), text)

        return letter_phrases

    def _extract_capitalized(self, doc, text=""):
        """Extract capitalized words."""
        capitalized_phrases = set()

        for token in doc:
            if phrase := token.text.strip():
                if phrase[0].isupper() and not (token.is_stop or token.is_punct or token.is_space) and self._is_valid_phrase(phrase):
                    capitalized_phrases.add(phrase.lower())

                    if text:
                        self._record_position(phrase.lower(), text)

        return capitalized_phrases

    def _extract_entity_context(self, entity, doc):
        """Helper function to extract contextual phrases around named entities within the same sentence."""
        context_phrases = []
        start_idx = entity.start
        end_idx = entity.end

        # Find the sentence containing this entity
        entity_sentence = None
        for sent in doc.sents:
            if sent.start <= start_idx < sent.end:
                entity_sentence = sent
                break

        if entity_sentence is None:
            return context_phrases

        # Get sentence boundaries
        sent_start = entity_sentence.start
        sent_end = entity_sentence.end

        # Look for descriptive phrases before and after the entity, within sentence boundaries
        for i in range(max(sent_start, start_idx - 2), start_idx):
            if doc[i].pos_ in ['ADJ', 'NOUN'] and not doc[i].is_stop:
                # Ensure the context phrase doesn't extend beyond sentence boundaries
                phrase_end = min(end_idx, sent_end)
                context_phrase = ' '.join([doc[j].text for j in range(i, phrase_end)])
                if len(context_phrase.split()) <= 5:  # Allow longer contextual phrases
                    context_phrases.append(context_phrase)

        return context_phrases

    def _normalize_phrase(self, phrase: str) -> str:
        """Normalize phrases to handle conflicting identifiers."""
        phrase = phrase.strip()

        # Remove leading articles more aggressively
        phrase = re.sub(r'^(the|a|an)\s+', '', phrase, flags=re.IGNORECASE)
        # remove commas and collapse multi-whitespace
        phrase = re.sub(r',',' ', phrase)
        phrase = re.sub(r'\s+', ' ', phrase)

        # Normalize common synonyms and conflicting identifiers
        synonyms = {
            'process': 'technique',
            'method': 'technique',
            'procedure': 'technique',
            'approach': 'technique',
            'system': 'method',
            'mechanism': 'process',
            'phenomenon': 'effect',
            'occurrence': 'event',
            'incident': 'event'
        }

        words = phrase.split()
        normalized_words = []
        for word in words:
            normalized_words.append(synonyms.get(word.lower(), word))

        return ' '.join(normalized_words)

    def _expunge_identifiers(self, phrase):
        """Take phrases starting with an demonstrative and identifier and remove them, leaving only the subsequent words."""

        id_phrase = re.sub(r'\b(?:this|the|these|those|that|an?)\s+[\w\'-]+', '', phrase.lower(), flags=re.IGNORECASE)
        id_phrase = re.sub(r'\s+', ' ', id_phrase)  # Multiple spaces to single space
        id_phrase = re.sub(r'\s+([,.!?;:])', r'\1', id_phrase)  # Remove space before punctuation
        id_phrase = re.sub(r'^[,.!?;:\s]+', '', id_phrase)  # Clean leading punctuation

        return id_phrase.strip()

    def _is_valid_phrase(self, phrase: str) -> bool:
        """Enhanced phrase validation with support for longer phrases."""
        phrase_lower = phrase.lower().strip()
        words = phrase_lower.split()

        word_count = len(words)
        if word_count > 6:
            return False

        # Basic length check
        if len(phrase_lower) < 4:
            return False

        # Remove phrases starting with articles or demonstratives
        if phrase_lower.startswith(("the ", "this ", "these ", "that ", "those ", "a ", "an ")):
            return False

        # Filter out purely functional words
        stop_words = self.nlp.Defaults.stop_words
        content_words = [w for w in words if w not in stop_words]

        # Must have at least 2 content words for longer phrases
        min_content_words = 2 if word_count > 3 else 1
        if len(content_words) < min_content_words:
            return False

        value_score = self._calculate_phrase_value(phrase_lower)
        if value_score < 0.2:  # Minimum value threshold
            return False

        filler_patterns = [
            r'\b(one of|type of|kind of|form of|example of)\b',
            r'\b(often|usually|typically|commonly|frequently)\b',
            r'\b(called|known as|referred to as)\b',
            r'\b(first|second|third|last|final)\b$'
        ]

        for pattern in filler_patterns:
            if re.search(pattern, phrase_lower):
                return False

        return True

    def _calculate_phrase_value(self, phrase: str) -> float:
        """Calculate the quizbowl value of a phrase."""
        words = phrase.split()
        value_score = 0.3  # Base score

        # Boost for value indicators
        for word in words:
            if word in self.value_indicators['high_value']:
                value_score += 0.4
            elif word in self.value_indicators['medium_value']:
                value_score += 0.3
            elif word in self.value_indicators['contextual']:
                value_score += 0.2

        # Boost for proper nouns
        if any(word[0].isupper() for word in phrase.split()):
            value_score += 0.2

        # Boost for technical suffixes
        technical_suffixes = ['tion', 'sion', 'ism', 'ology', 'graphy', 'metry']
        if any(phrase.endswith(suffix) for suffix in technical_suffixes):
            value_score += 0.3

        return min(value_score, 1.0)

    def _is_similar_to_answer(self, phrase: str, answer: str, threshold: float = 0.6) -> bool:
        """Check if phrase is too similar to the answer using multiple similarity metrics."""
        phrase_lower = phrase.lower()
        answer_lower = answer.lower()

        # Direct substring check
        if phrase_lower in answer_lower or answer_lower in phrase_lower:
            return True

        # Check if phrase contains significant portion of answer words
        answer_words = set(answer_lower.split())
        phrase_words = set(phrase_lower.split())

        if len(answer_words) > 0:
            overlap_ratio = len(answer_words.intersection(phrase_words)) / len(answer_words)
            if overlap_ratio > 0.7:
                return True

        # Sequence similarity check
        similarity = SequenceMatcher(None, phrase_lower, answer_lower).ratio()
        if similarity > threshold:
            return True

        # Check for partial name matches (e.g., "louis napoleon" vs "napoleon")
        if len(answer_words) > 1:
            for word in answer_words:
                if len(word) > 3 and word in phrase_lower:
                    # Check if it's a significant portion of the phrase
                    if len(word) / len(phrase_lower.replace(' ', '')) > 0.4:
                        return True

        return False

    def _remove_redundancy_advanced(self, buzzwords: List[Tuple[str, float]], answer: str) -> List[str]:
        """Advanced redundancy removal using semantic similarity and clustering."""
        if not buzzwords:
            return []

        # Filter out phrases too similar to answer first
        filtered_buzzwords = []
        for phrase, score in buzzwords:
            if not self._is_similar_to_answer(phrase, answer):
                filtered_buzzwords.append((phrase, score))

        # Group similar phrases and keep the highest scoring one from each group
        phrase_groups = []
        used_indices = set()

        for i, (phrase1, score1) in enumerate(filtered_buzzwords):
            if i in used_indices:
                continue

            current_group = [(phrase1, score1)]
            used_indices.add(i)

            for j, (phrase2, score2) in enumerate(filtered_buzzwords[i+1:], i+1):
                if j in used_indices:
                    continue

                # Check semantic similarity
                if self._are_phrases_similar(phrase1, phrase2):
                    current_group.append((phrase2, score2))
                    used_indices.add(j)

            phrase_groups.append(current_group)

        # Select best phrase from each group
        final_buzzwords = []
        for group in phrase_groups:
            # Sort by score and select the best one
            best_phrase = max(group, key=lambda x: x[1])
            final_buzzwords.append(best_phrase[0])

        return final_buzzwords

    def _are_phrases_similar(self, phrase1: str, phrase2: str, threshold: float = 0.4) -> bool:
        """Check if two phrases are semantically similar."""
        words1 = set(phrase1.lower().split())
        words2 = set(phrase2.lower().split())

        # Jaccard similarity
        intersection = words1.intersection(words2)
        union = words1.union(words2)

        if len(union) == 0:
            return False

        jaccard_sim = len(intersection) / len(union)

        if jaccard_sim > threshold:
            return True

        
        # Check for substring relationships
        if any(word1 in phrase2.lower() for word1 in words1 if len(word1) > 3):
            return True
        if any(word2 in phrase1.lower() for word2 in words2 if len(word2) > 3):
            return True  

        return False

    def _is_high_quality_buzzphrase(self, phrase: str) -> bool:
        """Final quality check for buzzphrases."""
        phrase_lower = phrase.lower()

        # Should not be too generic
        generic_terms = {
            'work', 'works', 'piece', 'pieces', 'part', 'parts',
            'kind', 'kinds', 'way', 'ways', 'time', 'times',
            'place', 'places', 'thing', 'things', 'people', 'person'
        }

        generic_phrases = {
            "amino acid", "organic chemistry", "modern day"
        }

        words = phrase_lower.split()
        if any(word in generic_terms for word in words):
            return False

        # Should have reasonable length
        if len(phrase_lower) < 5 or len(phrase_lower) > 40:
            return False
        
        if phrase in generic_phrases:
            return False

        return True

    def _record_position(self, phrase: str, text: str):
        """Record the position of a phrase in a question for celerity calculation."""
        if not text:
            return None

        question_words = text.split()
        phrase_words = phrase.split()

        if len(phrase_words) == 0 or len(question_words) == 0:
            return None

        # Find the first occurrence of the phrase in the question
        index = text.lower().find(phrase.lower())
        if index == -1:
            return

        # Count words before the phrase
        words_before = len(text[:index].split())
        wordcount = len(question_words)

        if wordcount > 0:
            celerity = 1 - (words_before / wordcount)
            self.phrase_positions[phrase].append(celerity)

    def _get_average_celerity(self, phrase: str):
        if phrase not in self.phrase_positions or len(self.phrase_positions[phrase]) == 0:
            return 0.0
        return sum(self.phrase_positions[phrase]) / len(self.phrase_positions[phrase])

    def _calculate_hybrid_score(self, phrase_data: Dict) -> float:
        """Calculate a hybrid score combining TF-IDF frequency with celerity positioning.
        
        This formula weights:
        - TF-IDF score (normalized to 0-1): How frequent and important the phrase is
        - Celerity score (0-1): How early in questions the phrase appears (1 = very early)
        
        The hybrid score ensures top results are phrases that:
        1. Appear early enough to be useful buzz clues (high celerity)
        2. Appear frequently enough to be reliable study material (high TF-IDF)
        
        Formula: hybrid_score = (frequency_weight * normalized_tfidf) + (celerity_weight * celerity)
        This uses the configured weights from self.hybrid_weights (default: 40% frequency, 60% celerity).
        """
        tfidf_score = phrase_data.get('score', 0)
        celerity_score = phrase_data.get('celerity', 0)
        
        # Get configured weights (with defaults)
        celerity_weight = self.hybrid_weights.get('celerity', 0.6)
        frequency_weight = self.hybrid_weights.get('frequency', 0.4)
        
        # Normalize TF-IDF to 0-1 range (assuming max TF-IDF around 2.0-3.0)
        # Using a conservative normalization to preserve relative differences
        normalized_tfidf = min(tfidf_score / 3.0, 1.0)
        
        # Celerity is already 0-1, where 1.0 = phrase at start of question
        # Ensure it's in valid range
        celerity_score = max(0.0, min(celerity_score, 1.0))
        
        # Hybrid formula: use configured weights
        # This allows customization of how much to prioritize early appearance vs frequency
        hybrid_score = (frequency_weight * normalized_tfidf) + (celerity_weight * celerity_score)
        
        return hybrid_score


    def extract_buzzwords(self, target_answer: str, category: str, max_questions: int = 60, sort_by="frequency", search_mode="exact"):
        """Enhanced buzzword extraction with improved scoring and semantic search support."""
        print(f"Starting enhanced extraction for: {target_answer}")
        print(f"Sorting by {sort_by}")
        print(f"Search mode: {search_mode}")

        questions = self._fetch_questions_by_answer_enhanced(target_answer, category, max_questions, search_mode)

        if not questions:
            print(f"No relevant questions found for '{target_answer}' in category '{category}'.")
            return []

        # Build enhanced corpus and record phrase positions
        corpus = []
        all_phrases = []
        self.phrase_positions = defaultdict(list)

        identifiers_all = []

        for q in tqdm(questions, desc="Processing questions"):
            phrases = self._extract_phrases(q.get('question', ''))
            multi_word_phrases = [phrase for phrase in phrases if 2 <= len(phrase.split()) <= 6]
            corpus.append(' '.join(multi_word_phrases))
            all_phrases.extend(multi_word_phrases)
            # Collect identifiers from raw question text
            identifiers_all.extend(self._extract_identifiers_from_question(q.get('question', '')))

        if not corpus or not any(corpus):
            print("No buzzphrases could be extracted from the questions.")
            return []

        vectorizer = TfidfVectorizer(
            ngram_range=(2, 6),  # Support up to 6-word phrases
            token_pattern=r"\b\w(?:[\w']+)?\b",
            sublinear_tf=True,
            use_idf=True,
            min_df=1,  # More lenient minimum
            max_df=0.85,
            stop_words='english',
            lowercase=True
        )

        try:
            non_empty_corpus = [doc for doc in corpus if doc.strip()]
            if not non_empty_corpus:
                print("Corpus is empty after filtering.")
                return []

            tfidf_matrix = vectorizer.fit_transform(non_empty_corpus)
            feature_names = vectorizer.get_feature_names_out()

            base_scores = tfidf_matrix.sum(axis=0).A1 # type: ignore
            phrase_freq = Counter(all_phrases)
            # Compute and cache mode identifier for this answer/topic
            if identifiers_all:
                id_counts = Counter(self._normalize_identifier_phrase(p) for p in identifiers_all if p)
                if len(id_counts) > 0:
                    self.last_identifier_by_answer[target_answer] = id_counts.most_common(1)[0][0]

            enhanced_scores = []
            for i, (term, score) in tqdm(enumerate(zip(feature_names, base_scores)), desc="Finding keywords"):
                freq_bonus = phrase_freq.get(term, 0)
                value_bonus = self._calculate_phrase_value(term)
                enhanced_scores.append((term, score * (1 + 0.1 * freq_bonus) * (1 + value_bonus)))

            # sort by TF-IDF to get general list of best phrases
            enhanced_scores.sort(key=lambda x: x[1], reverse=True)
            enhanced_scores = [(term, score) for (term, score) in enhanced_scores if score >= 0.250]

            # Apply advanced redundancy removal
            final_buzzwords = self._remove_redundancy_advanced(enhanced_scores, target_answer)

            # Final quality filter and celerity calculation
            final_list = []
            for phrase in tqdm(final_buzzwords, desc="Cleaning results and calculating celerity"):
                if self._is_high_quality_buzzphrase(phrase):
                    celerity = self._get_average_celerity(phrase)
                    if True:  # Only add phrases with a calculated celerity score
                        final_list.append({
                            'phrase': phrase,
                            'score': next((score for term, score in enhanced_scores if term == phrase), 0),
                            'celerity': celerity
                        })

            if sort_by == 'celerity':
                final_list.sort(key=lambda x: x['celerity'], reverse=True)
            elif sort_by == 'hybrid':
                # Hybrid sorting: early appearance + frequency (optimal for studying)
                final_list.sort(key=lambda x: self._calculate_hybrid_score(x), reverse=True)
            else:  # frequency (TF-IDF)
                final_list.sort(key=lambda x: x['score'], reverse=True)

            print(f"Generated {len(final_list)} enhanced buzzwords")
            return final_list[:250]

        except ValueError as e:
            print(f"Error during TF-IDF vectorization: {e}")
            return []

    def _extract_identifiers_from_question(self, text: str) -> List[str]:
        """Extract identifier phrases that follow 'this'/'these' in a question.

        We parse the raw question text and capture a short phrase immediately after
        'this' or 'these' consisting of content words (nouns, adjectives, proper nouns)
        until punctuation or unrelated parts of speech are encountered.
        """
        if not text:
            return []

        try:
            doc = self.nlp(text)
        except Exception:
            return []

        identifiers: List[str] = []
        allowed_pos = {"NOUN", "PROPN", "ADJ"}

        for i, token in enumerate(doc):
            if token.lower_ in ("this", "these"):
                phrase_tokens: List[str] = []
                j = i + 1
                while j < len(doc):
                    t = doc[j]
                    if t.is_space or t.is_punct:
                        break
                    if (t.pos_ in allowed_pos and not t.is_stop) or t.dep_ in ("amod", "compound"):
                        phrase_tokens.append(t.text)
                        j += 1
                        continue
                    break

                phrase = " ".join(phrase_tokens).strip()
                if phrase:
                    identifiers.append(phrase)

        return identifiers

    def _normalize_identifier_phrase(self, phrase: str) -> str:
        if not phrase:
            return ""
        p = phrase.strip()
        p = re.sub(r"^[\W_]+|[\W_]+$", "", p)
        p = re.sub(r"\s+", " ", p)
        return p.lower()

    def get_identifier_for_answer(self, target_answer: str, category: str = "", max_questions: int = 60) -> Optional[str]:
        """Return the mode identifier for an answer/topic, computing it from the corpus if needed."""
        if not target_answer:
            return None
        if target_answer in self.last_identifier_by_answer:
            return self.last_identifier_by_answer[target_answer]

        try:
            questions = self._fetch_questions_by_answer(target_answer, category, max_questions)
            identifiers_all = []
            for q in questions:
                identifiers_all.extend(self._extract_identifiers_from_question(q.get('question', '')))
            if identifiers_all:
                id_counts = Counter(self._normalize_identifier_phrase(p) for p in identifiers_all if p)
                if len(id_counts) > 0:
                    mode_identifier = id_counts.most_common(1)[0][0]
                    self.last_identifier_by_answer[target_answer] = mode_identifier
                    return mode_identifier
        except Exception as e:
            print(f"Identifier computation error for '{target_answer}': {e}")
        return None

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for a text using the sentence transformer model."""
        if not self.sentence_model or not text:
            return None
        
        # Clean and normalize text
        clean_text = self._clean_and_normalize_text(text)
        if not clean_text:
            return None
        
        # Check cache first
        cache_key = clean_text.lower().strip()
        if cache_key in self.embedding_cache:
            return self.embedding_cache[cache_key]
        
        try:
            # Generate embedding
            embedding = self.sentence_model.encode([clean_text])[0]
            self.embedding_cache[cache_key] = embedding
            return embedding
        except Exception as e:
            print(f"Error generating embedding for '{text}': {e}")
            return None

    def _fetch_questions_by_semantic_similarity(self, query: str, category: str, max_questions: int, similarity_threshold: float = 0.72):
        """Fetch questions using semantic similarity with hybrid exact+semantic matching."""
        if not self.sentence_model:
            print("Semantic search model not available, falling back to exact search")
            return self._fetch_questions_by_answer(query, category, max_questions)
        
        print(f"Performing hybrid semantic search for: '{query}'")
        
        # Get query embedding
        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            print("Failed to generate query embedding, falling back to exact search")
            return self._fetch_questions_by_answer(query, category, max_questions)
        
        # Fetch a larger set of questions to perform semantic filtering on
        all_questions = []
        
        # Strategy 1: Search for individual words in the query
        query_words = [word for word in query.split() if len(word) > 3]
        for word in query_words:
            try:
                params = {
                    'queryString': word,
                    'searchType': 'answer',
                    'categories': category,
                    'maxReturnLength': max_questions // max(1, len(query_words)),
                    'minYear': '2015',
                    'maxYear': '2025'
                }
                response = requests.get(f"{self.base_url}/query", params=params, timeout=10)
                time.sleep(self.rate_limit_delay)
                
                if response.status_code == 200:
                    data = response.json()
                    questions = data.get('tossups', {}).get('questionArray', [])
                    all_questions.extend(questions)
            except requests.exceptions.RequestException as e:
                print(f"Error in semantic search for '{word}': {e}")
        
        # Strategy 2: Also try the full query as fallback
        try:
            params = {
                'queryString': query,
                'searchType': 'answer',
                'categories': category,
                'maxReturnLength': max_questions,
                'minYear': '2010',
                'maxYear': '2025'
            }
            response = requests.get(f"{self.base_url}/query", params=params, timeout=10)
            time.sleep(self.rate_limit_delay)
            
            if response.status_code == 200:
                data = response.json()
                questions = data.get('tossups', {}).get('questionArray', [])
                all_questions.extend(questions)
        except requests.exceptions.RequestException as e:
            print(f"Error in semantic search for full query: {e}")
        
        # Remove duplicates
        seen_questions = set()
        unique_questions = []
        for q in all_questions:
            question_text = q.get('question', '')
            if question_text not in seen_questions:
                seen_questions.add(question_text)
                unique_questions.append(q)
        
        if not unique_questions:
            print("No questions found for semantic search")
            return []
        
        # Perform hybrid filtering (exact + semantic)
        print(f"Performing hybrid filtering on {len(unique_questions)} questions...")
        matching_questions = []
        
        for question in tqdm(unique_questions, desc="Computing similarities"):
            answer = question.get('answer', '').strip()
            if not answer:
                continue
            
            # Clean the answer
            clean_answer = re.sub(r'<[^>]+>', '', answer)
            clean_answer = re.sub(r'\[.*?\]|\(.*?\)', '', clean_answer).strip()
            
            if not clean_answer:
                continue
            
            # Check for exact matches first (same topic, different wording)
            if self._is_same_topic_exact(query, clean_answer):
                matching_questions.append((question, 1.0))  # Perfect match
                continue
            
            # If no exact match, try semantic similarity
            answer_embedding = self._get_embedding(clean_answer)
            if answer_embedding is not None:
                similarity = cosine_similarity([query_embedding], [answer_embedding])[0][0] # type: ignore
                
                if similarity >= similarity_threshold:
                    matching_questions.append((question, similarity))
        
        # Sort by similarity score (highest first)
        matching_questions.sort(key=lambda x: x[1], reverse=True)
        
        # Return the questions (without similarity scores)
        result_questions = [q for q, _ in matching_questions[:max_questions]]
        
        print(f"Found {len(result_questions)} matching questions")
        return result_questions

    def _is_same_topic_exact(self, query: str, answer: str) -> bool:
        """Check if query and answer refer to the same topic using minimal exact matching rules."""
        query_lower = query.lower().strip()
        answer_lower = answer.lower().strip()
        
        # Rule 1: Exact match
        if query_lower == answer_lower:
            return True
        
        # Rule 2: Singular/plural variations
        if query_lower + 's' == answer_lower or answer_lower + 's' == query_lower:
            return True
        if query_lower.rstrip('s') == answer_lower.rstrip('s') and len(query_lower) > 3:
            return True
        
        # Rule 3: Simple acronym expansions (minimal hardcoding)
        if len(query_lower) <= 10 and len(answer_lower) > len(query_lower) * 2:
            # Query might be an acronym
            words = answer_lower.split()
            if len(words) > 1:
                # Check if first letters match (ignoring common words)
                important_words = [word for word in words if word not in ['the', 'of', 'and', 'for', 'in', 'on', 'at', 'to', 'a', 'an']]
                if important_words:
                    first_letters = ''.join([word[0] for word in important_words if word])
                    if query_lower == first_letters:
                        return True
        
        # Rule 4: Reverse check - if answer is shorter, check if it's an acronym of query
        if len(answer_lower) <= 10 and len(query_lower) > len(answer_lower) * 2:
            words = query_lower.split()
            if len(words) > 1:
                important_words = [word for word in words if word not in ['the', 'of', 'and', 'for', 'in', 'on', 'at', 'to', 'a', 'an']]
                if important_words:
                    first_letters = ''.join([word[0] for word in important_words if word])
                    if answer_lower == first_letters:
                        return True
        
        return False

    def _fetch_questions_by_answer_enhanced(self, answer: str, category: str, max_questions: int, search_mode: str = 'exact'):
        """Enhanced question fetching with support for both exact and semantic search."""
        if search_mode == 'semantic':
            return self._fetch_questions_by_semantic_similarity(answer, category, max_questions)
        else:
            return self._fetch_questions_by_answer(answer, category, max_questions)


def main():
    """Main execution function."""
    print("\n" + "-"*43)
    print("ENHANCED TF-IDF QUIZBOWL BUZZWORD EXTRACTOR")
    print("-"*43 + "\n")

    answer = input("Enter the answer/topic to analyze: ").strip()
    if not answer:
        print("No answer provided. Exiting.")
        return

    category = input("Enter the category (Literature, History, Science, etc.): ").strip().capitalize()

    try:
        max_q = input("Maximum questions to analyze (default 60): ").strip()
        max_questions = int(max_q) if max_q else 60
    except ValueError:
        max_questions = 60

    sort_by = input("Sort by [frequency/celerity] (default frequency): ").strip().lower()
    if sort_by not in ['frequency', 'celerity']:
        sort_by = 'frequency'

    extractor = TFIDFQuizbowlExtractor()
    buzzphrases = extractor.extract_buzzwords(answer, category, max_questions, sort_by)

    if buzzphrases:
        print(f"\n{'-'*33}")
        print(f"ENHANCED BUZZWORDS FOR: {answer.upper()}")
        print(f"CATEGORY: {category.upper()}")
        print(f"SORTED BY: {sort_by.upper()}")
        print(f"{'-'*33}")

        for i, buzzphrase_data in enumerate(buzzphrases, 1):
            phrase = buzzphrase_data['phrase']
            word_count = len(phrase.split())
            score = buzzphrase_data.get('score', 0)
            celerity = buzzphrase_data.get('celerity', 0)

            if sort_by == 'celerity':
                print(f"{i:2}. {phrase} ({word_count} words) [Celerity: {celerity:.3f}]")
            else:
                print(f"{i:2}. {phrase} ({word_count} words) [Score: {score:.3f}]")

        print(f"\nGenerated {len(buzzphrases)} enhanced buzzwords!")
    else:
        print(f"No buzzwords could be extracted for '{answer}'")

if __name__ == "__main__":
    main()
