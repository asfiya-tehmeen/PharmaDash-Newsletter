"""Live check of Groq: plain call, tool use, JSON schema, web search. Run: python tests/live_groq.py"""
from pydantic import BaseModel
from pharmadash import config, llm
cfg = config.load_config(); m = cfg["models"]["research"]

r = llm.chat(m, [{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=200)
print("1 chat:", r.choices[0].message.content)

tools = {"add": ({"type": "function", "function": {"name": "add", "description": "Add two numbers",
    "parameters": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}}},
    lambda a, b: a + b)}
print("2 tool:", llm.run_agent(m, "Use tools for arithmetic.", "What is 1234 + 4321?", tools, log=print))

class Out(BaseModel):
    company: str
    year: int
print("3 json:", llm.ask_json(m, "Extract fields.", "Eli Lilly was founded in 1876.", Out))

print("4 search:", llm.web_search("Eli Lilly latest quarterly revenue announced")[:600])
print(llm.USAGE.summary())
