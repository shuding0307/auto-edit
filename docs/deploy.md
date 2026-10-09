# 배포 (단일 VM + Docker Compose + HTTPS)

외부에 열리는 건 Caddy(80/443)뿐이다. Caddy가 Let's Encrypt 인증서를 자동으로 받는다.

```
브라우저 ──https──▶ Caddy ─┬─ APP_DOMAIN/api/* ─▶ api (FastAPI) ─┐
                           ├─ APP_DOMAIN/*     ─▶ web (Next.js)   │  postgres · redis
                           └─ S3_DOMAIN/*      ─▶ s3 (SeaweedFS) ◀┤
                                                    worker (RQ, FFmpeg) · maintenance (1시간마다)
```

영상은 API를 거치지 않고 브라우저 ↔ `S3_DOMAIN` 으로 직접 오간다 (presigned URL). 그래서 도메인이 두 개 필요하다.

## 서버 요구사항

- Docker + Compose v2, 2코어 이상 · RAM 4GB 이상 권장 (4K 렌더는 CPU libx264라 맥의 하드웨어 인코딩보다 2~4배 느리다)
- 디스크: 영상이 7일 보관되므로 (업로드 최대 500MB × 하루 처리량 × 7) + 여유
- DNS A 레코드: `APP_DOMAIN`, `S3_DOMAIN` → 서버 IP. 방화벽 80·443 허용

## 처음 배포

```bash
git clone <repo> && cd ai-cut-editor
cp .env.prod.example .env.prod      # 도메인 입력, 비밀값은 openssl rand -hex 24
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api worker caddy
```

API 컨테이너가 시작할 때 DB 마이그레이션(`alembic upgrade head`)과 S3 버킷·CORS 설정을 자동으로 한다.

## 업데이트

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

## 확인

```bash
curl https://$APP_DOMAIN/api/health          # {"status":"ok"}
```

브라우저로 `https://$APP_DOMAIN` 에서 업로드 → 분석 → 검토 → 렌더 → 다운로드.

## 로컬에서 운영 구성 시험

```bash
# .env.prod.local: APP_DOMAIN=localhost, S3_DOMAIN=s3.localhost (Caddy가 내부 인증서 사용)
# 맥은 80번을 내장 Apache가 쓰므로 포트를 바꾼다:
#   HTTP_PORT=8080 HTTPS_PORT=8443 APP_URL=https://localhost:8443 S3_PUBLIC_URL=https://s3.localhost:8443
docker compose -p autoedit-prod -f docker-compose.prod.yml --env-file .env.prod.local up -d --build
```

내부 인증서라 브라우저 경고가 뜬다. curl은 `-k`. 접속은 https://localhost:8443

## 운영 메모

- 7일 지난 프로젝트는 `maintenance` 서비스가 S3·DB에서 지운다. 워커가 죽어 35분 넘게 멈춘 job은 실패로 바꾼다 (분석 → 다시 분석 가능, 렌더 → 검토 상태로 복귀).
- 백업이 필요하면 `pgdata`(DB)와 `s3data`(영상) 볼륨. 영상은 7일 뒤 지워지는 임시 데이터다.
- `GEMINI_API_KEY`를 비우면 STT·LLM 없이 무음 컷만 한다. 무료 티어는 입력이 Google 제품 개선에 쓰일 수 있다.
