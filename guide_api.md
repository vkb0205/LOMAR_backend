Trang chủ
Hướng dẫn
OpenAI Format
Định dạng API
OpenAI Format
Cài đặt
code

Copy
npm install openai
hoặc

code

Copy
yarn add openai
Khởi tạo Client
code

Copy
import OpenAI from 'openai';

const openai = new OpenAI({
  apiKey: 'your-shopaikey-api-key',
  baseURL: 'https://api.shopaikey.com/v1',
});
Chat Completions
Gọi API cơ bản
code

Copy
const completion = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Xin chào!' }
  ],
  max_tokens: 1000,
  temperature: 1.0,
});

console.log(completion.choices[0].message.content);
Streaming Response
code

Copy
const stream = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [
    { role: 'user', content: 'Kể cho tôi một câu chuyện dài' }
  ],
  stream: true,
});

for await (const chunk of stream) {
  const content = chunk.choices[0]?.delta?.content || '';
  if (content) {
    process.stdout.write(content);
  }
}
Vision API (Nhận diện hình ảnh)
code

Copy
const completion = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [
    {
      role: 'user',
      content: [
        {
          type: 'text',
          text: 'Bức ảnh này có nội dung gì? Hãy mô tả chi tiết.'
        },
        {
          type: 'image_url',
          image_url: {
            url: 'https://example.com/image.png'
          }
        }
      ]
    }
  ],
  max_tokens: 1000,
});

console.log(completion.choices[0].message.content);
Vision với Base64 Image
code

Copy
const fs = require('fs');

const imageBuffer = fs.readFileSync('./image.jpg');
const base64Image = imageBuffer.toString('base64');
const dataUrl = `data:image/jpeg;base64,${base64Image}`;

const completion = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [
    {
      role: 'user',
      content: [
        {
          type: 'text',
          text: 'Mô tả hình ảnh này'
        },
        {
          type: 'image_url',
          image_url: {
            url: dataUrl
          }
        }
      ]
    }
  ],
});
Function Calling
code

Copy
const completion = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [
    { role: 'user', content: 'Thời tiết ở Hà Nội hôm nay như thế nào?' }
  ],
  tools: [
    {
      type: 'function',
      function: {
        name: 'get_weather',
        description: 'Lấy thông tin thời tiết tại một địa điểm',
        parameters: {
          type: 'object',
          properties: {
            location: {
              type: 'string',
              description: 'Tên thành phố hoặc địa điểm',
            },
            unit: {
              type: 'string',
              enum: ['celsius', 'fahrenheit'],
            },
          },
          required: ['location'],
        },
      },
    },
  ],
  tool_choice: 'auto',
});

const message = completion.choices[0].message;
if (message.tool_calls) {
  console.log('Function calls:', message.tool_calls);
}
Xử lý lỗi
code

Copy
try {
  const completion = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'user', content: 'Hello' }],
  });
} catch (error) {
  if (error instanceof OpenAI.APIError) {
    console.error('API Error:', error.status);
    console.error('Message:', error.message);
  } else {
    console.error('Unexpected error:', error);
  }
}
TypeScript Support
code

Copy
import OpenAI from 'openai';

const openai = new OpenAI({
  apiKey: process.env.SHOPAIKEY_API_KEY!,
  baseURL: 'https://api.shopaikey.com/v1',
});

async function chat(message: string): Promise<string> {
  const completion = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role: 'user', content: message }],
  });

  return completion.choices[0].message.content || '';
}
Chi tiết API: Tạo trò chuyện (Stream)
(Create Chat Completion - Stream)

Endpoint này được sử dụng để tạo phản hồi từ mô hình cho một cuộc hội thoại đã cho. Dữ liệu có thể được trả về từng phần (streaming) để hiển thị thời gian thực.

Phương thức (Method): 
POST
URL: 
https://api.shopaikey.com/v1/chat/completions
Mô tả
Đưa ra một lời nhắc (prompt), mô hình sẽ trả về một hoặc nhiều dự đoán hoàn thành. API này cũng có thể trả về xác suất của các token thay thế tại mỗi vị trí.

Tài liệu gốc: OpenAI API Reference - Chat Create
Thông số Yêu cầu (Request Parameters)
Header Parameters
Tên tham số	Giá trị	Mô tả
Authorization
Bearer <Token>
Bắt buộc. Token xác thực API của bạn.
Content-Type
application/json
Bắt buộc. Định dạng dữ liệu gửi đi.
Accept
application/json
Body Parameters (
application/json
)
Tên tham số	Kiểu	Mô tả
model
string	ID của mô hình cần sử dụng (ví dụ: 
gpt-5-mini
, 
gpt-4o
).
messages
array	Danh sách các tin nhắn trong cuộc hội thoại.
max_tokens
integer	Số lượng token tối đa để tạo trong phần hoàn thành.
temperature
number	Nhiệt độ lấy mẫu (0 đến 2). Giá trị cao hơn (ví dụ 0.8) làm đầu ra ngẫu nhiên hơn, giá trị thấp hơn (ví dụ 0.2) làm đầu ra tập trung và xác định hơn.
stream
boolean	Nếu 
true
, dữ liệu sẽ được gửi về dưới dạng các sự kiện gửi từ máy chủ (server-sent events).
stream_options
object	Các tùy chọn bổ sung cho luồng, ví dụ 
{ "include_usage": true }
 để nhận thông tin sử dụng token.
Ví dụ Yêu cầu (Request Example)
JSON Body:

code

Copy
{
  "model": "gpt-5-mini",
  "max_tokens": 1000,
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Xin chào"
    }
  ],
  "temperature": 1.0,
  "stream": true,
  "stream_options": {
    "include_usage": true
  }
}
Ví dụ gọi API (cURL)
code

Copy
curl --location --request POST 'https://api.shopaikey.com/v1/chat/completions' \
--header 'Accept: application/json' \
--header 'Authorization: Bearer <YOUR_TOKEN_HERE>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "gpt-5-mini",
    "max_tokens": 1000,
    "messages": [
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
    ]
}
Phản hồi (Response)
Trạng thái: 
200 OK

code

Copy
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677652288,
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "\n\nHello there, how may I assist you today?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 9,
    "completion_tokens": 12,
    "total_tokens": 21
  }
}
Chi tiết API: Tạo trò chuyện nhận diện hình ảnh (Stream)
(Create Chat Vision - Stream)

Endpoint này cho phép bạn gửi hình ảnh kèm theo câu hỏi văn bản đến các mô hình đa phương thức (như GPT-4o, Claude 3.5 Sonnet) để nhận diện và mô tả nội dung hình ảnh theo thời gian thực.

Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/chat/completions
Mô tả
Gửi một lời nhắc bao gồm cả văn bản và URL hình ảnh. Mô hình sẽ trả về mô tả hoặc câu trả lời dựa trên nội dung hình ảnh đó.

Tài liệu gốc: OpenAI API Reference - Vision
Yêu cầu (Request)
Headers
Tên	Giá trị	Bắt buộc	Mô tả
Authorization
Bearer <Token>
Có	Token xác thực API của bạn.
Content-Type
application/json
Có	Định dạng dữ liệu gửi đi.
Accept
application/json
Không	
Body (application/json)
Cấu trúc quan trọng nhất là mảng 
messages
. Thay vì chỉ gửi chuỗi văn bản (
content: "string"
), bạn cần gửi một mảng các đối tượng nội dung (
content: array
) bao gồm 
text
 và 
image_url
.

code

Copy
{
  "model": "gpt-4o",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Bức ảnh này có nội dung gì? Hãy mô tả chi tiết."
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "https://example.com/image.png"
          }
        }
      ]
    }
  ],
  "stream": true,
  "max_tokens": 1000
}
Giải thích tham số:

model
: Các mô hình hỗ trợ Vision (ví dụ: 
gpt-4o
, 
gpt-4-turbo
, 
claude-3-5-sonnet-20240620
, 
gemini-1.5-pro
).
content
 (trong messages):
type: "text"
: Phần câu hỏi hoặc lời nhắc văn bản.
type: "image_url"
: Đối tượng chứa đường dẫn hình ảnh.
url
: Đường dẫn trực tiếp đến ảnh (phải công khai truy cập được) hoặc chuỗi Base64 (định dạng 
data:image/jpeg;base64,...
).
Ví dụ gọi API (cURL)
code

Copy
curl --location --request POST 'https://api.shopaikey.com/v1/chat/completions' \
--header 'Accept: application/json' \
--header 'Authorization: Bearer <YOUR_TOKEN_HERE>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "gpt-4o",
    "messages": [
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Trong ảnh này có những gì?"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://example.com/image.png"
                    }
                }
            ]
        }
    ],
    "stream": true
}'
Phản hồi (Response)
Trạng thái: 
200 OK

Phản hồi trả về tương tự như API Chat thông thường. Nếu 
stream: true
, dữ liệu sẽ về từng chunk. Dưới đây là ví dụ JSON của một phản hồi hoàn chỉnh (hoặc chunk cuối):

code

Copy
{
  "id": "chatcmpl-890",
  "object": "chat.completion",
  "created": 1677652288,
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Trong ảnh là một phong cảnh thiên nhiên tuyệt đẹp với bầu trời xanh..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 50,
    "total_tokens": 170
  }
}
Responses API
OpenAI Responses API dùng để tạo phản hồi mô hình. Hỗ trợ hội thoại nhiều lượt, gọi công cụ, suy luận.

Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/responses
Request Body
Tên tham số	Kiểu	Mô tả
model
string	Bắt buộc. ID model
input
string/array	Nội dung đầu vào
instructions
string	Hướng dẫn cho model
max_output_tokens
integer	Số token đầu ra tối đa
temperature
number	Nhiệt độ lấy mẫu
top_p
number	Tham số nucleus sampling
stream
boolean	Phản hồi dạng stream
tools
array	Danh sách công cụ
tool_choice
string/object	Lựa chọn công cụ
reasoning
object	Cấu hình suy luận (
effort
: low/medium/high)
previous_response_id
string	ID phản hồi trước (multi-turn)
truncation
string	Chế độ cắt ngắn (auto/disabled)
Ví dụ
code

Copy
const response = await openai.responses.create({
  model: 'gpt-4o',
  input: 'Xin chào!',
  instructions: 'Bạn là trợ lý hữu ích.',
});

console.log(response.output[0].content[0].text);
Response
code

Copy
{
  "id": "resp_abc123",
  "object": "response",
  "created_at": 1700000000,
  "status": "completed",
  "model": "gpt-4o",
  "output": [
    {
      "type": "message",
      "id": "msg_abc123",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Xin chào! Tôi có thể giúp gì cho bạn?"
        }
      ]
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 15,
    "total_tokens": 25
  }
}
Responses Compaction
Nén hội thoại dài (compaction) cho Responses API.

Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/responses/compact
Tên tham số	Kiểu	Mô tả
model
string	Bắt buộc. ID model
input
string/array	Nội dung cần nén
instructions
string	Hướng dẫn nén
previous_response_id
string	ID phản hồi trước
Images API
Tạo ảnh
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/images/generations
code

Copy
const image = await openai.images.generate({
  model: 'gpt-image-1',
  prompt: 'Một chú mèo nhỏ đội mũ nồi đứng giữa phố cổ',
  n: 1,
  size: '1024x1024',
  quality: 'high',
  response_format: 'url',
});

console.log(image.data[0].url);
Tên tham số	Kiểu	Mô tả
model
string	Model sinh ảnh (
dall-e-2
, 
dall-e-3
, 
gpt-image-1
)
prompt
string	Bắt buộc. Mô tả ảnh cần tạo
n
integer	Số lượng ảnh (1-10)
size
string	Kích thước ảnh đầu ra
quality
string	Chất lượng ảnh
background
string	Nền ảnh (transparent/opaque/auto)
style
string	Phong cách ảnh
response_format
string	Định dạng trả về (url/b64_json)
Chỉnh sửa ảnh
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/images/edits
Content-Type: 
multipart/form-data
Tên tham số	Kiểu	Mô tả
image
file	Bắt buộc. Ảnh gốc cần chỉnh sửa
prompt
string	Bắt buộc. Mô tả chỉnh sửa
mask
file	Ảnh mask PNG để chỉ vùng chỉnh sửa
model
string	Model chỉnh sửa ảnh
n
string	Số ảnh đầu ra
size
string	Kích thước (256x256, 512x512, 1024x1024)
Videos API
Tạo video (OpenAI format)
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/videos
Content-Type: 
multipart/form-data
Tên tham số	Kiểu	Mô tả
model
string	Tên model (vd: 
sora-2
)
prompt
string	Prompt mô tả video
seconds
string	Số giây sinh
input_reference
file	Tệp ảnh tham chiếu
Lấy trạng thái video
Phương thức: 
GET
URL: 
https://api.shopaikey.com/v1/videos/{task_id}
Lấy nội dung video
Phương thức: 
GET
URL: 
https://api.shopaikey.com/v1/videos/{task_id}/content
Trả về luồng tệp video (
video/mp4
).

Tạo video (Generic format)
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/video/generations
Tên tham số	Kiểu	Mô tả
model
string	ID model (vd: 
kling-v1
)
prompt
string	Prompt mô tả
image
string	Ảnh đầu vào (URL hoặc Base64)
duration
number	Thời lượng video (giây)
width
integer	Chiều rộng video
height
integer	Chiều cao video
fps
integer	Tốc độ khung hình
seed
integer	Hạt giống ngẫu nhiên
n
integer	Số lượng video
Lấy trạng thái video (Generic format)
Phương thức: 
GET
URL: 
https://api.shopaikey.com/v1/video/generations/{task_id}
Embeddings API
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/embeddings
code

Copy
const embedding = await openai.embeddings.create({
  model: 'text-embedding-ada-002',
  input: 'Xin chào thế giới',
});

console.log(embedding.data[0].embedding);
Tên tham số	Kiểu	Mô tả
model
string	Bắt buộc. ID model (vd: 
text-embedding-ada-002
)
input
string/array	Bắt buộc. Văn bản cần nhúng
encoding_format
string	Định dạng (float/base64)
dimensions
integer	Số chiều vector đầu ra
Audio API
Text-to-Speech
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/audio/speech
code

Copy
const mp3 = await openai.audio.speech.create({
  model: 'tts-1',
  voice: 'alloy',
  input: 'Xin chào, tôi là trợ lý AI.',
});
Tên tham số	Kiểu	Mô tả
model
string	Bắt buộc. Model TTS (vd: 
tts-1
)
input
string	Bắt buộc. Văn bản cần chuyển đổi (tối đa 4096 ký tự)
voice
string	Bắt buộc. Giọng nói (alloy/echo/fable/onyx/nova/shimmer)
response_format
string	Định dạng (mp3/opus/aac/flac/wav/pcm)
speed
number	Tốc độ (0.25 - 4.0)
Phiên âm (Transcription)
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/audio/transcriptions
Content-Type: 
multipart/form-data
Tên tham số	Kiểu	Mô tả
file
file	Bắt buộc. Tệp âm thanh
model
string	Bắt buộc. Model (vd: 
whisper-1
)
language
string	Mã ngôn ngữ ISO-639-1
response_format
string	Định dạng (json/text/srt/verbose_json/vtt)
Dịch âm thanh (Translation)
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/audio/translations
Content-Type: 
multipart/form-data
Tên tham số	Kiểu	Mô tả
file
file	Bắt buộc. Tệp âm thanh
model
string	Bắt buộc. Model (vd: 
whisper-1
)
Completions API (Legacy)
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/completions
Tên tham số	Kiểu	Mô tả
model
string	Bắt buộc. ID model
prompt
string/array	Bắt buộc. Prompt đầu vào
max_tokens
integer	Số token tối đa
temperature
number	Nhiệt độ lấy mẫu
stream
boolean	Phản hồi dạng stream
Rerank API
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/rerank
code

Copy
const result = await fetch('https://api.shopaikey.com/v1/rerank', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer <your-api-key>',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'rerank-english-v2.0',
    query: 'What is machine learning?',
    documents: ['ML is a subset of AI', 'Cooking recipes', 'Deep learning models'],
    top_n: 2,
  }),
});
Tên tham số	Kiểu	Mô tả
model
string	Bắt buộc. Model rerank
query
string	Bắt buộc. Văn bản truy vấn
documents
array	Bắt buộc. Danh sách tài liệu
top_n
integer	Trả về N kết quả đầu tiên
return_documents
boolean	Trả về nội dung tài liệu
Moderations API
Phương thức: 
POST
URL: 
https://api.shopaikey.com/v1/moderations
Tên tham số	Kiểu	Mô tả
input
string/array	Bắt buộc. Nội dung cần kiểm duyệt
model
string	Model kiểm duyệt (vd: 
text-moderation-latest
)
Realtime API (WebSocket)
Phương thức: 
GET
 (WebSocket upgrade)
URL: 
wss://api.shopaikey.com/v1/realtime?model=gpt-4o-realtime-preview
Thiết lập kết nối WebSocket cho hội thoại thời gian thực.

Tên tham số	Kiểu	Mô tả
model
query string	Model sử dụng (vd: 
gpt-4o-realtime-preview
)
Liệt kê Models
Phương thức: 
GET
URL: 
https://api.shopaikey.com/v1/models
code

Copy
const models = await openai.models.list();
console.log(models.data);
Bài cùng nhóm · Định dạng API
Anthropic Format
Google GenAI SDK
Bài trước
Seller API