#!/usr/bin/env python3
"""
Simple test to check if sentence-transformers is working
"""

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity
    
    print("✅ All imports successful")
    
    # Load model
    print("🤖 Loading sentence transformer model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    print("✅ Model loaded successfully")
    
    # Test sentences
    sentences = [
        "We offer AI chatbot development services",
        "Our office hours are Monday to Friday 9 AM to 6 PM",
        "Contact us at info@company.com",
        "We use Python, JavaScript, and SQL"
    ]
    
    # Create embeddings
    print("🧠 Creating embeddings...")
    embeddings = model.encode(sentences)
    print(f"✅ Created embeddings shape: {embeddings.shape}")
    
    # Test query
    query = "What programming languages do you use?"
    query_embedding = model.encode([query])
    
    # Calculate similarities
    similarities = cosine_similarity(query_embedding, embeddings)[0]
    
    print(f"\n📊 Testing query: '{query}'")
    print("Similarity scores:")
    for i, (sentence, score) in enumerate(zip(sentences, similarities)):
        print(f"   {i+1}. {score:.3f} - {sentence}")
    
    # Find best match
    best_idx = np.argmax(similarities)
    best_score = similarities[best_idx]
    best_sentence = sentences[best_idx]
    
    print(f"\n🎯 Best match: {best_score:.3f}")
    print(f"📝 Response: {best_sentence}")
    
    if best_score > 0.3:
        print("✅ AI similarity matching is working correctly!")
    else:
        print("⚠️  Low similarity score - this might be the issue")
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("💡 Try: pip install sentence-transformers")
except Exception as e:
    print(f"❌ Unexpected error: {e}") 