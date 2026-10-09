# CapCut 가져오기 검증 (F7)

개발 계획 Phase 4의 "CapCut에서 MP4 + SRT로 후반 편집 가능" 확인용. 사람이 CapCut 데스크톱에서 직접 해 보고 결과를 아래 표에 적는다.

## 준비

```bash
.venv/bin/python scripts/cut.py fixtures/videos/sample.MOV \
  --transcript fixtures/transcripts/sample.json --fcpxml -o capcut_test/sample_edited.mp4
```

`capcut_test/`에 다음이 생긴다 (git 제외 폴더):

| 파일 | 내용 |
|---|---|
| `sample_edited.mp4` | 승인된 컷이 반영된 영상 |
| `sample_edited.srt` | 편집본 시간 기준 자막 |
| `sample_edited.csv` | 컷 리포트 (엑셀) |
| `sample_edited.fcpxml` | 원본(`fixtures/videos/sample.MOV`)을 참조하는 컷 타임라인. 원본을 옮기면 연결이 끊긴다 |

웹에서 렌더했다면 검토 화면 오른쪽 아래 "내보낸 파일"에서 MP4·SRT·CSV를 받으면 된다 (FCPXML은 CLI만).

## 체크리스트

1. CapCut 데스크톱에서 새 프로젝트 → `sample_edited.mp4` 가져와 타임라인에 올린다.
2. 자막 가져오기 (텍스트/자막 메뉴의 "로컬 자막 가져오기" 계열) → `sample_edited.srt`.
3. 영상을 처음·중간·끝에서 재생하며 자막이 말과 맞는지 본다.
4. 자막 하나를 고쳐 보고(글자·스타일), 영상을 잘라 보며 후반 편집이 되는지 본다.
5. 새 프로젝트에서 `sample_edited.fcpxml` 가져오기를 시도한다 (메뉴에 XML/FCPXML 가져오기가 있는지부터).
6. 가져와지면 클립이 12개로 나뉘어 있는지, 총 길이가 41.17초인지 본다.

## 결과 (직접 기입)

| 항목 | 결과 | 메모 |
|---|---|---|
| CapCut 버전 / OS | | |
| MP4 가져오기·재생 | | |
| SRT 가져오기 | | |
| 자막 싱크 (처음/중간/끝) | | |
| 자막 수정 후 내보내기 | | |
| FCPXML 가져오기 메뉴 존재 | | |
| FCPXML 가져오기 결과 (클립 수·길이) | | |

FCPXML이 되면 Phase 5 후보("컷 단위로 CapCut에서 이어 편집"), 안 되면 이 문서에 기록하고 MP4 + SRT로 마무리한다.
