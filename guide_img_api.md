Nano Banana
Nano Banana API cho phép bạn tạo hình ảnh từ text prompt sử dụng các model Gemini Image của Google.

Endpoint
Base URL: 
https://api.shopaikey.com
Tạo ảnh: 
POST /images/google/generations
Xác thực
Tất cả các request đều yêu cầu API key trong header:

code

Copy
Authorization: Bearer <your-api-key>
Tạo hình ảnh
Request
Endpoint: 
POST /images/google/generations

Headers:

code

Copy
Authorization: Bearer <your-api-key>
Content-Type: application/json
Body Parameters:

Tham số	Kiểu	Bắt buộc	Mô tả
model
string	Có	Model sử dụng: 
nano-banana
, 
nano-banana-2
 hoặc 
nano-banana-pro
prompt
string	Có	Mô tả hình ảnh bạn muốn tạo
size
string	Không	Tỷ lệ khung hình. Mặc định: 
1:1
. Các giá trị hợp lệ: 
1:1
, 
2:3
, 
3:2
, 
3:4
, 
4:3
, 
4:5
, 
5:4
, 
9:16
, 
16:9
, 
21:9
imageSize
string	Không	Kích thước ảnh (cho 
nano-banana-2
 và 
nano-banana-pro
): 
0.5K
, 
1K
, 
2K
, 
4K
. Mặc định: 
2K
format
string	Không	Định dạng ảnh: 
png
 hoặc 
jpeg
. Mặc định: 
png
response_format
string	Không	Định dạng response: 
url
 hoặc 
b64_json
. Mặc định: 
url
image_urls
array	Không	Mảng các URL hình ảnh tham chiếu (tối đa 3 cho 
nano-banana
, 5 cho 
nano-banana-2
 và 
nano-banana-pro
)
Model nano-banana
Model cơ bản, hỗ trợ tối đa 3 ảnh tham chiếu.

Model nano-banana-2
Model thế hệ mới, cân bằng giữa tốc độ và chất lượng. Hỗ trợ tối đa 5 ảnh tham chiếu và tùy chọn kích thước ảnh (
imageSize
).

Model nano-banana-pro
Model chuyên nghiệp, hỗ trợ tối đa 5 ảnh tham chiếu và chất lượng cao nhất.

Image sizes hỗ trợ (cho nano-banana-2 và nano-banana-pro):

0.5K
: 512x512 (cho aspect ratio 1:1)
1K
: 1024x1024 (cho aspect ratio 1:1)
2K
: 2048x2048 (cho aspect ratio 1:1)
4K
: 4096x4096 (cho aspect ratio 1:1)
Aspect ratios hỗ trợ (cho mỗi image size):

1:1
, 
2:3
, 
3:2
, 
3:4
, 
4:3
, 
4:5
, 
5:4
, 
9:16
, 
16:9
, 
21:9
Ví dụ Request - nano-banana-2
code

Copy
curl --location --request POST 'https://api.shopaikey.com/images/google/generations' \
--header 'Authorization: Bearer <your-api-key>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "nano-banana-2",
    "prompt": "Một phi hành gia đang cưỡi ngựa trên mặt trăng, phong cách cyberpunk",
    "size": "1:1",
    "imageSize": "1K",
    "format": "png"
}'
Ví dụ Request - nano-banana-pro
code

Copy
curl --location --request POST 'https://api.shopaikey.com/images/google/generations' \
--header 'Authorization: Bearer <your-api-key>' \
--header 'Content-Type: application/json' \
--data-raw '{
    "model": "nano-banana-pro",
    "prompt": "Một bức tranh phong cảnh siêu thực với màu sắc sống động",
    "size": "16:9",
    "imageSize": "4K",
    "format": "png"
}'
Ví dụ JavaScript
code

Copy
const response = await fetch('https://api.shopaikey.com/images/google/generations', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer <your-api-key>',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'nano-banana-2',
    prompt: 'Một bức tranh phong cảnh siêu thực với màu sắc sống động',
    size: '16:9',
    imageSize: '2K',
    format: 'png',
    response_format: 'url',
  }),
});

const data = await response.json();
console.log('Image URL:', data.data[0].url);
Response
Khi response_format là "url":

code

Copy
{
  "created": 1234567890,
  "data": [
    {
      "url": "https://example.com/image.png"
    }
  ]
}
Khi response_format là "b64_json":

code

Copy
{
  "created": 1234567890,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
Tạo ảnh với hình ảnh tham chiếu
Bạn có thể cung cấp các hình ảnh tham chiếu để model tạo ảnh dựa trên style hoặc nội dung của chúng:

code

Copy
const response = await fetch('https://api.shopaikey.com/images/google/generations', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer <your-api-key>',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'nano-banana-2',
    prompt: 'Tạo một bức ảnh tương tự nhưng với chủ đề khác',
    size: '16:9',
    imageSize: '2K',
    image_urls: [
      'https://example.com/reference1.jpg',
      'https://example.com/reference2.jpg'
    ],
  }),
});
So sánh các Model
Tính năng	nano-banana	nano-banana-2	nano-banana-pro
Ảnh tham chiếu	Tối đa 3	Tối đa 5	Tối đa 5
Image sizes	Cố định	0.5K, 1K, 2K, 4K	0.5K, 1K, 2K, 4K
Chất lượng	Tốt	Rất tốt	Tuyệt vời
Tốc độ	Nhanh	Cân bằng	Trung bình
Xử lý lỗi
API sẽ trả về mã lỗi HTTP và thông báo lỗi trong response:

code

Copy
{
  "error": {
    "message": "Model và prompt là bắt buộc"
  }
}
Các mã lỗi phổ biến:

400: Request không hợp lệ (thiếu tham số, giá trị không hợp lệ, quá nhiều ảnh tham chiếu)
401: Thiếu hoặc API key không hợp lệ
500: Lỗi server hoặc model không tìm thấy
Best Practices
Prompt Quality: Viết prompt rõ ràng và chi tiết để có kết quả tốt hơn
Aspect Ratio: Chọn aspect ratio phù hợp với mục đích sử dụng
Image Size: Với 
nano-banana-pro
, chọn image size phù hợp (2K cho hầu hết trường hợp, 4K cho chất lượng cao)
Reference Images: Sử dụng ảnh tham chiếu chất lượng cao để có kết quả tốt hơn
Format: Sử dụng 
png
 cho ảnh có transparency, 
jpeg
 cho ảnh thông thường
Bài cùng nhóm · Đa phương tiện