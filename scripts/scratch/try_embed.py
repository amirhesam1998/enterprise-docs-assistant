from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-m3")

texts = [
    "A type cast specifies a conversion from one data type to another.",
    "How do I convert a value from one type to another?",
    "The chicken soup recipe needs two carrots.",
]

vecs = model.encode(texts)
print(vecs.shape)

sim = model.similarity(vecs, vecs)
print(sim)