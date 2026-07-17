import openai, os
from dotenv import load_dotenv

load_dotenv(override=True)
client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
response = client.chat.completions.create(
    model='gpt-4o',
    max_tokens=50,
    messages=[{'role': 'user', 'content': 'say hello'}]
)
print(response.choices[0].message.content)