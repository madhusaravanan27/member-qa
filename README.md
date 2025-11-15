# Member QA – Design Notes and Data Insights

This document summarizes both the system design decisions and the findings from analyzing the member message dataset. The final solution has also been deployed successfully on Render for public access and testing.

## Design Notes

This project required building a question-answering system over a collection of member messages. Several approaches were evaluated before choosing the final hybrid solution.

### 1. Pure Rule-Based Extraction

The simplest approach was to rely entirely on regex patterns to detect questions related to trips, restaurants, favorites, or car counts. This method was fast, deterministic, and easy to debug, but it became brittle as soon as question phrasing changed. It did not scale well to more conversational or open-ended queries, so it wasn’t sufficient on its own.

### 2. Full Retrieval-Augmented Generation (RAG) With an LLM

Another idea was to build a full RAG pipeline, embedding all member messages and using an LLM to produce final answers. This would have handled natural language extremely well and supported almost any type of question. However, this was outside the constraints of the assignment and required heavier infrastructure than necessary. For those reasons, this approach was rejected.

### 3. Hybrid “RAG-Lite” Approach (Final Choice)

The final architecture combines rule-based extraction for structured queries with embedding-based semantic retrieval for flexible or loosely phrased questions. This allows the system to answer precise questions accurately while still retrieving useful contextual messages for broader queries. The approach avoids the brittleness of regex-only systems while remaining far simpler than full RAG.

### 4. Intent Classifier (Considered but Not Used)

A lightweight classifier could have been trained to identify different question types, offering more flexibility than regex. However, this required labeled training data, which was not available. Additionally, classification alone would still require extraction logic. Therefore, it was not selected.

### 5. Final Decision Summary

The hybrid RAG-Lite system satisfies assignment requirements, handles a wide range of queries, avoids unnecessary complexity, and is easy to deploy. It offers the best balance between accuracy for structured questions and flexibility for natural language queries.

---

## Data Insights

### 1. Dataset Overview

A total of 600 messages were fetched from the upstream API. Basic validation showed that the dataset was clean and consistent. There were no missing user names, no missing message text, no duplicate IDs, no invalid timestamps, and no extremely short or long messages. This high level of cleanliness supported reliable retrieval and extraction.

### 2. Message Length Patterns

All messages fell within normal conversational ranges. There were no messages under 5 characters and none above 500 characters. This indicates the absence of noise, spam, or corrupted entries.

### 3. Timestamp Validation

Timestamps ranged from November 2024 to November 2025. All timestamps were valid, consistently formatted, and uniformly structured, with no timezone issues or malformed entries.

### 4. User Activity Distribution

User message activity was uneven, with a small number of members contributing a large portion of the dataset. The most active users were:

- Vikram Desai (70 messages)
- Sophia Al-Farsi (66 messages)
- Armand Dupont (62 messages)
- Lily O’Sullivan (60 messages)
- Fatima El-Tahir (59 messages)

This uneven distribution affects retrieval depth—active users provide much richer semantic context than users with only a few messages.

### 5. Structural Consistency

There were no issues related to ID formatting, encoding, missing fields, or timestamp duplication. The dataset appears to be curated or synthetically generated because of its uniformity and consistency.

### 6. Final Observations

The dataset is clean and free from anomalies. The only notable characteristic is uneven message distribution across users, which affects retrieval performance but does not impact system correctness.

---

## API Endpoints

### `/ask`
Handles structured, intent-based queries such as:
- Trip details  
- Trip summaries  
- Yes/No travel questions  
- Car counts  
- Favorite restaurants  
- Favorite things  

It uses rule-based extraction first and falls back to semantic retrieval when needed.

### `/ask_generic`
A general semantic-search endpoint that retrieves the most relevant messages for any open-ended question.

**Recommended usage**
- Use `/ask` for questions involving trips, cars, restaurants, or favorites.
- Use `/ask_generic` for general exploratory queries or when intent is ambiguous.

---

## Outputs

### ask/ endpoint
(Images shown below represent example outputs produced by the deployed system.)

<img width="878" height="278" alt="image" src="https://github.com/user-attachments/assets/ba847d57-a81c-4e70-8bdb-6f703a07fb97" />

<img width="873" height="217" alt="image" src="https://github.com/user-attachments/assets/fe7ab9dc-db5a-430c-b7c4-738ec7d5381e" />

<img width="883" height="229" alt="image" src="https://github.com/user-attachments/assets/13b9ee71-ffb3-4636-8136-ae58d4c34836" />

### ask/generic endpoint

<img width="857" height="237" alt="image" src="https://github.com/user-attachments/assets/27a052b7-f25b-4bf6-875f-f9296fd26e77" />

---

## Future Improvements

Future enhancements could make the system more powerful and scalable. More advanced intent detection could be added to support a wider variety of question types, potentially using lightweight classifiers or few-shot reasoning. The extraction layer could be improved using spaCy or dependency parsing, making the system less dependent on regex. Incremental or streaming message indexing would allow embeddings to stay updated as new data arrives, improving retrieval freshness. Multi-message summarization could be added for richer answers when multiple messages provide context. Error handling could be improved with retry logic and more descriptive responses. Finally, if allowed, optional LLM-based refinement could enhance reasoning for more complex user queries.

---

## Conclusion

The Member QA project successfully combines rule-based logic with semantic retrieval to deliver a flexible, accurate question-answering system. The hybrid RAG-Lite design handles both structured and open-ended queries while remaining simple to deploy and maintain. The dataset’s cleanliness supports consistent performance, and the API structure is intuitive and easy to use. The full system has been deployed on Render and performs reliably in a real environment, making it production-ready while meeting all assignment requirements.
