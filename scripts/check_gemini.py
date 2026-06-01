import os, json
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("=== Modelos disponíveis para sua chave ===")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(f"  {m.name}  |  {m.display_name}")

print("\n=== Teste de chamada direta ===")
try:
    model = genai.GenerativeModel("gemini-2.0-flash")
    r = model.generate_content('Responda apenas: {"ok": true}')
    print("Resposta:", r.text)
except Exception as e:
    print("ERRO:", e)
