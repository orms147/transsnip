---
name: write-mentor-doc
description: Use this skill when the user asks to write or update a mentor-style doc in docs/mentor/ for TransSnip (e.g., "viết mentor doc cho X", "tạo bài hướng dẫn về Y", "update doc 23-build-ocr-pipeline"). Enforces the 7-section template, Vietnamese tone, code that actually runs, and links to real files in the repo.
---

# Write a mentor-style doc

Use khi tạo/sửa file trong [docs/mentor/](../../../docs/mentor/) cho TransSnip. Bài mentor hướng dẫn intern mới học AI/Python — tone thân mật, giải thích "tại sao" trước "làm thế nào".

## Template bắt buộc (7 sections)

```markdown
# {Số}. {Tên bài} — {tóm tắt 1 câu}

> **Đọc xong bài này em sẽ:**
> - {outcome cụ thể 1}
> - {outcome cụ thể 2}
> - {outcome cụ thể 3}
>
> **Cần đọc trước:** [link đến prerequisite docs](XX-foo.md)
> **Thời gian:** ~{N} phút

## 1. Tại sao chúng ta cần thứ này?
Kể câu chuyện thực tế. Đặt vấn đề. Tránh giảng đạo.

VD: "Hãy tưởng tượng em chụp ảnh trang sách tiếng Nhật bằng điện thoại. Làm sao máy
đọc được chữ trong ảnh đó? Đó là việc của OCR — và đó là lý do chúng ta cần nó."

## 2. Concept (giải thích đơn giản)
Dùng analogy đời thường. Vẽ ASCII diagram nếu cần.

VD: "OCR = đôi mắt của máy tính. Nó nhìn vào pixel và đoán xem đó là chữ gì."

```
[ảnh chữ "Hello"]  →  [OCR engine]  →  "Hello" (chuỗi ký tự)
   bitmap                                  text
```

## 3. Trong project của chúng ta, nó nằm ở đâu?
Trỏ tới file CODE THẬT trong repo:
- [transsnip/ocr/base.py](../../transsnip/ocr/base.py) — ABC định nghĩa interface
- [transsnip/ocr/windows_ocr.py](../../transsnip/ocr/windows_ocr.py) — implementation cho Windows OCR

Giải thích vai trò mỗi class/function chính.

## 4. Code mẫu — chạy thử ngay
Code nhỏ, độc lập, copy-paste là chạy được:

```python
# minimal_ocr.py
from PIL import Image
import winrt.windows.media.ocr as ocr_module
# ... (đầy đủ để chạy)
```

Giải thích từng dòng quan trọng. Đừng dump code xong rồi bỏ đi.

## 5. Những thứ thường sai (mentor đã từng gặp)
- **Trap 1:** {mô tả} → **Fix:** {cách sửa}
- **Trap 2:** {mô tả} → **Fix:** {cách sửa}

## 6. Tự kiểm tra
- [ ] {Câu hỏi concept}
- [ ] {Bài tập nhỏ: "Sửa code mẫu để nhận text tiếng Nhật"}
- [ ] {Quick check: chạy code và confirm output}

## 7. Đọc tiếp
→ Bài tiếp theo: [XX-next.md](XX-next.md)
→ Đào sâu (optional): {link tài liệu external}
```

## Style guide

- **Ngôn ngữ:** Tiếng Việt. Xưng **"bạn" (người đọc) / "tôi" (mentor)**. KHÔNG dùng "em" / "chúng ta". Tone thân mật nhưng nghiêm túc.
- **Code:** Comment trong code tiếng Việt OK. Identifier (tên hàm/biến) tiếng Anh.
- **Độ dài:** 5-10 phút đọc (~ 300-700 từ thân bài, chưa kể code).
- **Diagram:** ASCII diagram khi mô tả flow. Không cần vẽ tool ngoài.
- **External link:** Có thể link MDN, Python docs, Anthropic docs nhưng KHÔNG bắt user phải đọc external mới hiểu bài.

## Quy tắc bắt buộc

1. **Code mẫu phải chạy được** — copy ra file `.py` mới rồi `python file.py` phải work (hoặc giải thích rõ prerequisite). Không viết pseudo-code mà gọi là "code mẫu".
2. **Trỏ tới file thật trong repo** — Section 3 PHẢI link đến file code đã tồn tại. KHÔNG viết về tính năng chưa implement.
3. **Section 5 phải có ít nhất 2 trap** — viết trap gây ra bởi misunderstanding concept, không phải lỗi typo.
4. **Section 6 phải có ít nhất 1 bài tập** — không chỉ câu hỏi concept.
5. **Số thứ tự file** theo convention trong plan: `00-09` overview/setup, `10-19` concepts, `20-29` MVP build steps, `30-39` Phase 2 build, `40-49` polish.

## Verification

- [ ] File follow đúng 7 sections (không skip section nào)
- [ ] Code trong section 4 chạy thử thành công bằng `python <file>`
- [ ] Tất cả link đến file repo đều resolve (file tồn tại)
- [ ] Section 5 có >=2 trap thực tế
- [ ] Section 6 có >=1 bài tập (không chỉ Q&A)
- [ ] README.md trong docs/mentor/ đã link đến bài mới
