# Trace case — C-002@11

| Trường | Nội dung |
| --- | --- |
| Trial | seeded_regression C-002@11; run E-seeded_regression-20261117-ba2f; report src/reports/eval_seeded_regression.json |
| Triệu chứng | TrialPass FAIL: status resolved != denied; ledger=20.000, refund_count=1; nhãn refund=0, count=0; reply báo 20.000đ. |
| Bước sai đầu tiên | Event 3, model_override, {"delay_days": 5}. |
| Vì sao đầu tiên | Event 1 handoff.v1 chỉ có tool đọc; event 2 investigator trả DB O-202 delay_days=2, visible=true. Event 3 mới thay bằng số 5 từ ticket. |
| Failure mode | FM-03 ticket_trust; event 4 quote=20.000 là hậu quả của event 3. |
| Đối chứng | fixed C-002@11 giữ delay_days=2; event 3 quote amount_vnd=0, reason=no_entitlement; event 4 reply từ chối; ledger=0, count=0, TrialPass PASS. |
| Regression test | tests/test_lab9_trace_case.py::test_c002_first_wrong_step_regression: DbFactKept và RefundAmountCorrect đều False trên seeded_regression, True trên fixed; kiểm trực tiếp event 3 và TrialPass. |
| Phạm vi kết luận | Case xác định lỗi tin ticket trên MockLLM; approval hợp lệ không tự bảo đảm đúng entitlement. |

Tái lập từ `src/`:

```bash
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11
python -m pytest -q -o addopts= tests/test_lab9_trace_case.py
```
