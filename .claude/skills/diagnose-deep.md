---
name: diagnose-deep
description: Deep diagnostic analysis combining /diagnose data from both Bybit and KIS bots. Use when user wants comprehensive bot performance review across all strategies.
---

# /diagnose-deep skill

봇 양쪽 (Bybit + KIS) 통합 진단.

## 작동 흐름

1. `intelligence.db` 또는 `kis/intelligence/intelligence.db` 접근
2. 양쪽 데이터 집계:
   - Bybit: bybit_d, bybit_mr 봇
   - KIS: kis_kr_clenow, kis_us_swing
3. 분석 차원:
   - 시간대별 PnL (시간 패턴 발견)
   - 심볼별 승률 (강/약 종목)
   - tier별 효율 (점수 시스템 검증)
   - 전략별 성과 (D vs D_INV vs MR vs Clenow vs Swing)
   - 청산 사유 분포 (TP / SL / trail / 시간정지)
4. 자동 인사이트:
   - "🚨 부진 심볼 N종 → 가중치/휴식 검토"
   - "✅ 최고 성과 전략 → 사이즈 확장 검토"
   - "⚠️ 특정 시간대 손실 집중 → 차단 검토"

## 출력 예

```
📊 양봇 통합 진단 (지난 30일)

총 거래: 89건 (Bybit 50 / KIS KR 25 / KIS US 14)
총 PnL: -\$42 (Bybit -\$107 / KIS KR +\$48 / KIS US +\$17)

━ 봇별 ━
Bybit: 41% wr -\$107 (점수 역상관 -5.3)
KIS KR Clenow: 64% wr +\$48 (정상)
KIS US Swing: 50% wr +\$17 (낮은 거래)

━ 자동 인사이트 ━
🚨 Bybit D 전략 — 점수 역상관 D_INV 검증 중
✅ KIS Clenow 강함 → 사이즈 확장 검토
⚠️ Bybit 06~12 KST -\$87 → 시간차단 (이미 v6.33 적용)
```
