# Supabase 실시간 장르 편집 설정

대시보드는 Supabase `public.dashboard_genre_edits` 테이블을 읽고 씁니다.

## 1. SQL Editor에서 실행

Supabase Dashboard → SQL Editor → New query에서 아래 파일 내용을 실행하세요.

`supabase/migrations/20260617_dashboard_genre_edits.sql`

## 2. 필요한 테이블

```sql
public.dashboard_genre_edits
```

## 3. 보안 참고

현재 웹 대시보드 직접 편집을 위해 anon insert/update/select 정책을 포함합니다.
팀 외부에 공개되면 누구나 수정 가능하므로, 장기 운영 시 Supabase Auth 기반 authenticated-only 정책으로 바꾸는 것을 권장합니다.

## 4. 대시보드 설정

`docs/supabase-config.js`에 Project URL과 anon public key가 들어 있습니다.
service_role key는 절대 넣지 마세요.

## 5. 확인 방법

브라우저 콘솔에서:

```js
SUPABASE_ENABLED
```

이 `true`이면 연결 설정이 켜진 상태입니다.

테이블이 없으면 대시보드 상태에 `Supabase 연결 실패: 설정/권한 확인 필요`가 표시됩니다.
