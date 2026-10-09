# AI Cut Editor

업로드 → 무음·말실수 자동 컷 → 사람 검토 → MP4·SRT·JSON 내보내기.
개발 계획: https://claude.ai/artifact/CmYuKZUivRMYb5Ywn6H4XM

## 명령어
- make setup    # .venv 생성 + Python/Node 의존성 설치 (최초 1회)
- make dev      # docker compose up (postgres, redis, s3=SeaweedFS :8333)
- make test     # pytest worker/ apps/api + vitest apps/web
- make lint     # ruff, mypy, eslint, tsc
- make e2e      # fixtures 전체 분석 → 정답 비교 표 → EVAL_LOG.md (LLM 포함: make e2e LLM=1, 비용 발생)
- python scripts/cut.py input.mp4 [--stt | --transcript words.json] [--provider gemini|claude] [--dry-run]
- python scripts/transcribe.py fixtures/videos/*.MOV   # Gemini STT → fixtures/transcripts/
- tools/label.html  브라우저로 열어 정답 컷 라벨링 → fixtures/expected/<이름>.json

## 구조
- worker/pipeline/  순수 함수: silence(파서), merge, timemap, probe, transcript, llm_cuts,
                    candidates(무음+LLM → 후보·자동승인), evaluate(정답 비교)
- worker/analyze.py 분석 조립 (CLI·e2e 공용)
- worker/gemini.py  Gemini 호출은 여기서만: STT(gemini-3.5-transcribe) + CutModel(gemini-3.8-flash, 기본)
- worker/llm_client.py  Claude 호출은 여기서만 (CutModel 구현). 테스트는 가짜 클라이언트
- worker/ffmpeg.py  FFmpeg/ffprobe 호출은 전부 여기
- worker/render.py  유지 구간 → filtergraph 구성(순수) + ffmpeg.py로 렌더
- apps/api          FastAPI
- apps/web          Next.js + TypeScript + Tailwind

## 규칙
- 시간은 항상 원본 기준 정수 밀리초(*_ms). float 초 금지.
- worker/pipeline/ 은 순수 함수만. FFmpeg·DB·네트워크 호출 금지.
- FFmpeg 호출은 worker/ffmpeg.py 한 곳에서만.
- LLM은 단어 인덱스 범위로만 답한다. 타임코드를 LLM에게 생성시키지 않는다.
- 새 기능은 테스트와 함께. make test 통과 전에는 완료라고 하지 않는다.
- API 스키마 바꾸면 make gen-types 실행.
- API 키는 .env 에만. 코드·로그에 출력 금지.
- 영상 길이는 최대 10분·500MB를 가정한다 (긴 영상 분할 설계는 범위 밖).

## 함정
- 자동 승인은 무음 + confidence ≥ 0.9 반복만. 나머지 LLM 후보는 suggested (렌더 미반영).
- STT 기본은 Gemini 무료(gemini-3.5-transcribe). 단어 타임스탬프는 실험적 기능이고 정확도가 떨어질 수 있어
  비교 대상이 필요하다. 다른 STT도 transcript.load_words 포맷으로 변환해 넘기면 된다.
- Gemini 무료 티어는 입력(음성 포함)이 Google 제품 개선에 쓰일 수 있다. 민감한 영상엔 쓰지 말 것.
- MinIO 공식 이미지는 pull 불가(배포 중단). 로컬 S3는 SeaweedFS, 키는 infra/seaweedfs/s3.json.
  boto3는 Config(signature_version="s3v4", s3={"addressing_style": "path"}) 필수
  (기본값이면 presigned PUT이 403). 컨테이너 시작 후 S3 API가 뜨기까지 몇 초 걸린다.
- iPhone 영상은 avg_frame_rate가 678240/28261 같은 흔들린 값. probe.py가 공칭 fps로 보정한다.
- 4K 렌더는 느리다. macOS에선 h264_videotoolbox(기본 auto), 결과는 임시 파일에 쓴 뒤 이름 변경.
- 컷 경계는 프레임 경계로 스냅한다. 스냅 안 하면 세그먼트마다 비디오가 프레임 단위로
  반올림되어 오디오와 어긋남이 누적된다.
- 렌더는 재인코딩. 스트림 복사(-c copy)는 키프레임 단위로만 잘린다.
- FFmpeg가 없으면 worker/tests의 통합 테스트는 skip 된다 (brew install ffmpeg).
