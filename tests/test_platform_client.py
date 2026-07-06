from job_radar.platform_client import (
    clean_title,
    parse_jobkorea_jobs,
    parse_saramin_jobs,
)


SARAMIN_ITEM_WITH_TITLE_ATTR = """
<ul>
<li class="item">
  <a href="/zf_user/jobs/relay/view?view_type=list&rec_idx=54360155" target="_blank"
     title="기업 임직원 건강관리 서비스 영업관리 신입/경력직 채용">
    <span class="logo"><img src="logo.gif" alt="(주)에임메드"></span>
    <strong class="tit">기업 임직원 건강관리 서비스 영업관리 신입/경력직 채용</strong>
    <span class="corp">(주)에임메드</span>
    <ul class="desc">
      <li class="company_local ellipsis">서울전체</li>
      <li>신입/경력</li>
    </ul>
    <span class="date ">~07.31(금)</span>
  </a>
  <button type="button" scraped="n" rec_idx="54360155" class="btn_scrap" title="스크랩">
    <img src="star.png" alt="스크랩"></button>
</li>
</ul>
"""

# 앵커에 title 속성이 없어 예전 파서가 스크랩 버튼의 title을 제목으로 저장하던 사례
SARAMIN_ITEM_WITHOUT_TITLE_ATTR = """
<ul>
<li class="item">
  <a href="/zf_user/jobs/relay/view?view_type=list&rec_idx=54291306" target="_blank">
    <span class="logo"><img src="logo.jpg" alt="한일산업(주)"></span>
    <strong class="tit">2026년도 신입 및 경력사원 모집</strong>
    <span class="corp">한일산업(주)</span>
    <ul class="desc">
      <li class="company_local ellipsis">서울전체 외</li>
      <li>신입/경력</li>
    </ul>
    <span class="date ">내일마감</span>
  </a>
  <button type="button" scraped="n" rec_idx="54291306" class="btn_scrap" title="스크랩">
    <img src="star.png" alt="스크랩"></button>
</li>
</ul>
"""

JOBKOREA_DETAIL_ITEM = """
<ul>
<li class="job-recommendation-item devloopArea" data-info="49524249|...">
  <div class="job-recommendation-details">
    <span class="company-name">
      <a href="/Recruit/GI_Read/49524249?rPageCode=PL" target="_blank">세명몰드㈜</a>
    </span>
    <p class="title">
      <a href="/Recruit/GI_Read/49524249?rPageCode=PL" target="_blank">
        중력주조금형 캐드원, UG NX 설계 경력자 구합니다.
      </a>
      <button type="button" class="scrap-button"><span class="blind">스크랩</span></button>
    </p>
    <div class="info">
      <ul class="tags-wrapper">
        <li class="tag">경력3년↑</li>
        <li class="tag">정규직</li>
        <li class="tag">경남 김해시</li>
      </ul>
      <div class="deadline">D-30</div>
    </div>
  </div>
</li>
</ul>
"""

# 배너형 목록: span.name + description 앵커에 마감일이 섞여 있음
JOBKOREA_BANNER_ITEM = """
<ul>
<li class=" devloopArea" data-info="49404184|...">
  <div class="company TopHeadlineAGI">
    <span class="name">
      <a href="/Recruit/GI_Read/49404184?rPageCode=PL" target="_blank">
        <span class="logo"><img src="logo.gif" alt=""></span>
        이노스페이스
      </a>
    </span>
  </div>
  <div class="description">
    <a href="/Recruit/GI_Read/49404184?rPageCode=PL" target="_blank">
      <span class="text"> 2026 이노스페이스 신입/경력 수시채용 공고</span>
      <span class="dday"><span class="deadLine">상시채용</span></span>
    </a>
  </div>
</li>
</ul>
"""


def test_saramin_title_never_scrap_button():
    jobs = parse_saramin_jobs(
        SARAMIN_ITEM_WITHOUT_TITLE_ATTR,
        base_url="https://www.saramin.co.kr/zf_user/jobs/list/job-category",
        max_items=10,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "2026년도 신입 및 경력사원 모집"
    assert job["company_name"] == "한일산업(주)"
    assert job["source_record_id"] == "54291306"


def test_saramin_url_normalized_to_direct_view():
    jobs = parse_saramin_jobs(
        SARAMIN_ITEM_WITH_TITLE_ATTR,
        base_url="https://www.saramin.co.kr/zf_user/jobs/list/job-category",
        max_items=10,
    )
    assert jobs[0]["url"] == "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=54360155"
    assert jobs[0]["deadline"] == "~07.31(금)"


def test_jobkorea_detail_item():
    jobs = parse_jobkorea_jobs(
        JOBKOREA_DETAIL_ITEM,
        base_url="https://www.jobkorea.co.kr/recruit/joblist",
        max_items=10,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job["company_name"] == "세명몰드㈜"
    assert job["title"] == "중력주조금형 캐드원, UG NX 설계 경력자 구합니다."
    assert job["deadline"] == "D-30"
    assert job["location"] == "경남 김해시"


def test_jobkorea_banner_item_company_not_fallback():
    jobs = parse_jobkorea_jobs(
        JOBKOREA_BANNER_ITEM,
        base_url="https://www.jobkorea.co.kr/recruit/joblist",
        max_items=10,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job["company_name"] == "이노스페이스"
    assert job["title"] == "2026 이노스페이스 신입/경력 수시채용 공고"
    assert job["deadline"] == "상시채용"
    assert "잡코리아" not in job["company_name"]


def test_clean_title_strips_trailing_deadline():
    assert clean_title("현대건설 경력직 채용 ~07/12") == ("현대건설 경력직 채용", "~07/12")
    assert clean_title("각 부문별 채용 상시채용") == ("각 부문별 채용", "상시채용")
    assert clean_title("설비기사 채용 오늘마감") == ("설비기사 채용", "오늘마감")
    assert clean_title("기계설계 신입 D-3") == ("기계설계 신입", "D-3")


def test_clean_title_strips_truncation_ellipsis():
    title, deadline = clean_title("[SK에코플랜트] AI데이터센터 경력직(정.. ~07/12")
    assert title == "[SK에코플랜트] AI데이터센터 경력직(정"
    assert deadline == "~07/12"


def test_clean_title_keeps_normal_sentence_period():
    title, deadline = clean_title("UG NX 설계 경력자 구합니다.")
    assert title == "UG NX 설계 경력자 구합니다."
    assert deadline == ""
