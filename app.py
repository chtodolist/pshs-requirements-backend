
from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "service": "PSHS Requirements Backend"
    })

@app.get("/health")
def health():
    return jsonify({"status": "healthy"}), 200
