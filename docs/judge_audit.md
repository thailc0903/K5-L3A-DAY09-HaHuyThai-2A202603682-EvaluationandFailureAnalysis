# Judge audit

FAIL là lớp dương. Nguồn: hai CSV công khai; chạy `python -m lab9.judge --csv data/eval/judge_<tone|helpful>_public.csv --audit 5`.

| Tiêu chí | n | TP/FP/FN/TN | κ | Precision | Recall | Observed → RG | Quyết định |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tone_ok | 100 | 24/4/6/66 | 0.757 | 0.857 | 0.8 | 0.28 → 0.3 | Dùng cho tone |
| helpful | 100 | 9/0/21/70 | 0.375 | 1.0 | 0.3 | 0.09 → 0.3 | Loại khỏi gate |

Floors: κ≥0,6; P≥0,8; R≥0,7. κ không xác định phải FAIL. Helpful bỏ sót 21/30 lỗi (FN), recall 0,3 và κ 0,375; precision 1,0 không bù được số lỗi lọt. RG chỉ hiệu chỉnh tỉ lệ lỗi, không làm một classifier yếu đủ chuẩn làm gate.

## Audit 5 bất đồng

| Case | Judge | Người | Ai đúng | Sửa rubric |
| --- | --- | --- | --- | --- |
| H-008 | PASS | FAIL | Nhãn người, theo rubric và note CSV | Cấm cách xưng hô quá suồng sã và từ đệm “nha”; thân thiện không đủ để PASS. |
| H-017 | PASS | FAIL | Nhãn người, theo rubric và note CSV | Dùng anh/chị theo chuẩn CS; không mặc định “bạn…nha” phù hợp mọi khách. |
| H-029 | PASS | FAIL | Nhãn người, theo rubric và note CSV | Đánh FAIL với câu ra lệnh “không cần nhắn thêm”, dù mở đầu lịch sự. |
| H-042 | FAIL | PASS | Nhãn người, theo rubric và note CSV | Không bắt buộc xin lỗi nếu thông báo ngắn đã lịch sự và đủ ý. |
| H-051 | FAIL | PASS | Nhãn người, theo rubric và note CSV | Cho phép thuật ngữ refund theo chuẩn CS; không FAIL chỉ vì từ tiếng Anh. |

Rubric v1.1 được lưu tại `src/config/judge_rubric.yaml`, áp dụng các quy tắc trong bảng audit; nhãn replay giữ nguyên để bảo toàn phép đo calibration. Helpful HL-015 nói 55.000đ trong khi note ledger=40.000đ: người FAIL đúng; rubric phải buộc đối chiếu số tiền bằng code, không đánh đồng văn phong lịch sự với tính đúng đắn.

Judge replay đo độ khớp với nhãn CSV cố định. Tone đạt floors được dùng cho giọng điệu; gate tiền/approval chỉ dùng code. Tiền, proposal, status và approval dùng code.
