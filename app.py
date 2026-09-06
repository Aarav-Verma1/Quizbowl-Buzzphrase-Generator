from flask import Flask, render_template, request, jsonify
import requests
import time
import re
from obsidian import TFIDFQuizbowlExtractor
import os
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Initialize the extractor once when the app starts
extractor = TFIDFQuizbowlExtractor()

# Gemini API configuration - PASTE YOUR API KEY HERE
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/gemini-flash-latest:generateContent"
)
GEMINI_API_KEY = "-----"

def generate_explanation(buzzword, topic):
    prompt = f"""The user entered the topic '{topic}'.  

The extracted buzzword is '{buzzword}'.
Write a clear, concise (1-2 sentences), and accurate explanation of why this buzzword is important for identifying '{topic}' in a quizbowl context. Briefly describe what the buzzword is and its direct connection to {topic}."""

    headers = {
        'Content-Type': 'application/json',
        'X-goog-api-key': GEMINI_API_KEY
    }
   
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "maxOutputTokens": 500,
            "temperature": 0.5,
            "thinkingConfig": {
                "thinkingBudget": 0   # disables thinking entirely for a short factual task like this
            }
        }
    }

    for attempt in range(3):
        try:
            response = requests.post(
                GEMINI_API_URL,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 503:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return f"Gemini is temporarily unavailable to explain '{buzzword}'."
                
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            
            if not candidates:
                return f"This buzzword is significant for identifying {topic} in quiz bowl questions."
                
            return candidates[0]["content"]["parts"][0]["text"].strip()
            
        except requests.RequestException as error:
            status = getattr(error.response, 'status_code', None)
            body = getattr(error.response, 'text', None)
            print(f"Gemini request failed (attempt {attempt + 1}): status={status} body={body} err={error}")
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return f"This buzzword helps identify {topic} in quiz bowl contexts."
    
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/autocomplete')
def autocomplete():
    """Provide autocomplete suggestions based on QBReader API with optional semantic search."""
    query = request.args.get('query', '').strip()
    search_mode = request.args.get('search_mode', 'exact').strip()
   
    if len(query) < 2:
        return jsonify([])
   
    try:
        if search_mode == 'semantic' and extractor.sentence_model:
            # Use semantic search for autocomplete
            return semantic_autocomplete(query)
        else:
            # Use exact text search (original behavior)
            return exact_autocomplete(query)
   
    except Exception as e:
        print(f"Autocomplete error: {e}")
   
    return jsonify([])

def exact_autocomplete(query):
    """Original exact text matching autocomplete."""
    try:
        # Search for answers that match the query
        params = {
            'queryString': query,
            'searchType': 'answer',
            'maxReturnLength': 20
        }
        response = requests.get(f"{extractor.base_url}/query", params=params, timeout=5)
        time.sleep(0.05)  # Small delay to be respectful
       
        if response.status_code == 200:
            data = response.json()
            questions = data.get('tossups', {}).get('questionArray', [])
           
            # Extract unique answers
            answers = set()
            for q in questions:
                answer = q.get('answer', '').strip()
                if answer:
                    # Clean the answer by removing HTML tags and formatting
                    clean_answer = re.sub(r'<[^>]+>', '', answer)
                    clean_answer = re.sub(r'\[.*?\]|\(.*?\)', '', clean_answer).strip()
                    if clean_answer and query.lower() in clean_answer.lower():
                        answers.add(clean_answer.title())
           
            return jsonify(sorted(list(answers))[:10])
    except Exception as e:
        print(f"Exact autocomplete error: {e}")
    return jsonify([])

def semantic_autocomplete(query):
    """Semantic search-based autocomplete using embeddings."""
    try:
        # Get query embedding
        query_embedding = extractor._get_embedding(query)
        if query_embedding is None:
            return exact_autocomplete(query)  # Fallback to exact search
        
        # Search for a broader set of answers
        params = {
            'queryString': query,
            'searchType': 'answer',
            'maxReturnLength': 50  # Get more results for semantic filtering
        }
        response = requests.get(f"{extractor.base_url}/query", params=params, timeout=5)
        time.sleep(0.05)
       
        if response.status_code == 200:
            data = response.json()
            questions = data.get('tossups', {}).get('questionArray', [])
            
            # Extract and score answers by semantic similarity
            scored_answers = []
            for q in questions:
                answer = q.get('answer', '').strip()
                if answer:
                    # Clean the answer
                    clean_answer = re.sub(r'<[^>]+>', '', answer)
                    clean_answer = re.sub(r'\[.*?\]|\(.*?\)', '', clean_answer).strip()
                    
                    if clean_answer:
                        # Check for exact matches first (same topic, different wording)
                        if extractor._is_same_topic_exact(query, clean_answer):
                            scored_answers.append((clean_answer.title(), 1.0))  # Perfect match
                        else:
                            # Get embedding for the answer
                            answer_embedding = extractor._get_embedding(clean_answer)
                            if answer_embedding is not None:
                                # Compute cosine similarity
                                from sklearn.metrics.pairwise import cosine_similarity
                                similarity = cosine_similarity([query_embedding], [answer_embedding])[0][0]
                                
                                # Only include answers with reasonable similarity (same topic, different wording)
                                if similarity > 0.6:  # Moderate threshold for autocomplete
                                    scored_answers.append((clean_answer.title(), similarity))
            
            # Sort by similarity and return top 10
            scored_answers.sort(key=lambda x: x[1], reverse=True)
            return jsonify([answer for answer, _ in scored_answers[:10]])
            
    except Exception as e:
        print(f"Semantic autocomplete error: {e}")
        return exact_autocomplete(query)  # Fallback to exact search
    
    return jsonify([])

@app.route('/extract', methods=['POST'])
def extract_buzzwords():
    """Extract buzzwords for the given answer and category."""
    data = request.get_json()
    answer = data.get('answer', '').strip()
    category = data.get('category', '').strip()
    max_questions = data.get('max_questions', 50)
    sort_by = data.get('sort_by', 'frequency')  # 'frequency' or 'celerity'
    search_mode = data.get('search_mode', 'exact')  # 'exact' or 'semantic'
   
    if not answer:
        return jsonify({'error': 'Answer is required'}), 400
   
    try:
        buzzwords_data = extractor.extract_buzzwords(answer, category, max_questions, sort_by, search_mode)
       
        # Limit to 20 buzzwords initially for display
        limited_buzzwords = buzzwords_data[:20]
       
        # Return initial buzzwords with additional data
        return jsonify({
            'answer': answer,
            'category': category,
            'buzzwords': limited_buzzwords,
            'all_buzzwords': buzzwords_data,  # Store all buzzwords for "load more"
            'count': len(limited_buzzwords),
            'total_count': len(buzzwords_data),
            'sort_by': sort_by,
            'search_mode': search_mode
        })
    except Exception as e:
        print(f"Extraction error: {e}")
        return jsonify({'error': f'An error occurred during extraction: {str(e)}'}), 500

@app.route('/generate-explanation', methods=['POST'])
def generate_explanation_endpoint():
    """Generate explanation for a specific buzzword when requested."""
    data = request.get_json()
    buzzword = data.get('buzzword', '').strip()
    topic = data.get('topic', '').strip()
   
    if not buzzword or not topic:
        return jsonify({'error': 'Both buzzword and topic are required'}), 400
   
    try:
        explanation = generate_explanation(buzzword, topic)
        return jsonify({'explanation': explanation})
    except Exception as e:
        print(f"Error generating explanation: {e}")
        return jsonify({'error': 'Failed to generate explanation'}), 500

@app.route('/export-anki', methods=['POST'])
def export_anki():
    """Export buzzwords as CSV for Anki import."""
    from flask import make_response
    import csv
    import io
   
    data = request.get_json()
    answer = data.get('answer', '').strip()
    # New structured mode: list of items with answerline and buzzphrase
    flashcards = data.get('flashcards', [])
    # Legacy mode: This contains only user-selected buzzwords
    selected_buzzwords = data.get('selected_buzzwords', [])
    
    if not flashcards and (not answer or not selected_buzzwords):
        return jsonify({'error': 'Provide flashcards list, or answer with selected_buzzwords'}), 400
   
    try:
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
       
        # Write header
        writer.writerow(['Front', 'Back'])
       
        if flashcards:
            # New structured export format using provided buzzphrases and computed identifiers
            # Limit to maximum 50 items
            limited_flashcards = flashcards[:50]
            for item in limited_flashcards:
                answerline = (item.get('answerline', '') or '').strip()
                buzzphrase = (item.get('buzzphrase', '') or '').strip()
                if not answerline:
                    # Skip invalid entries silently
                    continue
                # Compute identifier mode across corpus for this answerline
                identifier = extractor.get_identifier_for_answer(answerline, data.get('category', '').strip()) or ''
                front = f"{buzzphrase}\n[{identifier}]" if identifier else f"{buzzphrase}"
                back = answerline
                writer.writerow([front, back])
        else:
            # Legacy: Write only the buzzwords the user has selected, mapped to requested format
            # Compute single identifier for the provided answer (mode across corpus)
            # Limit to maximum 50 items
            limited_buzzwords = selected_buzzwords[:50]
            identifier_mode = extractor.get_identifier_for_answer(answer, data.get('category', '').strip()) or ''
            for i, buzzword in enumerate(limited_buzzwords, 1):
                front = f"{buzzword}\n[{identifier_mode}]" if identifier_mode else f"{buzzword}"
                back = answer
                writer.writerow([front, back])
       
        # Create response
        csv_content = output.getvalue()
        output.close()
       
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        # If exporting from cart mode (flashcards present, possibly spanning topics), use a generic name
        if flashcards:
            base_name = 'shopping_cart'
        else:
            base_name = (answer or 'flashcards').replace(' ', '_')
        response.headers['Content-Disposition'] = f'attachment; filename="{base_name}_flashcards.csv"'
       
        return response
       
    except Exception as e:
        print(f"Export error: {e}")
        return jsonify({'error': 'Failed to export CSV'}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
