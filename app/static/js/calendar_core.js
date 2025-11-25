// app/static/js/calendar_core.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("📅 calendar_core.js loaded");

  const calendarEl = document.getElementById("calendar");
  if (!calendarEl) {
    console.warn("⚠ FullCalendar element not found");
    return;
  }

  // ✅ 전체/내 일정 토글 상태 (기본: 전체)
  window.currentCalendarScope = "all";

  const btnAll = document.getElementById("btnScopeAll");
  const btnMine = document.getElementById("btnScopeMine");

  function updateScopeButtons() {
    if (!btnAll || !btnMine) return;

    if (window.currentCalendarScope === "all") {
      btnAll.classList.add("bg-sky-500", "text-white");
      btnAll.classList.remove("bg-sky-100", "text-sky-700");

      btnMine.classList.add("bg-sky-100", "text-sky-700");
      btnMine.classList.remove("bg-sky-500", "text-white");
    } else {
      btnMine.classList.add("bg-sky-500", "text-white");
      btnMine.classList.remove("bg-sky-100", "text-sky-700");

      btnAll.classList.add("bg-sky-100", "text-sky-700");
      btnAll.classList.remove("bg-sky-500", "text-white");
    }
  }

  // ✅ 버튼 클릭 시 scope 변경 + 이벤트 리로드
  if (btnAll && btnMine) {
    btnAll.addEventListener("click", () => {
      window.currentCalendarScope = "all";
      updateScopeButtons();
      window.calendar?.refetchEvents();
    });

    btnMine.addEventListener("click", () => {
      window.currentCalendarScope = "mine";
      updateScopeButtons();
      window.calendar?.refetchEvents();
    });
  }

  // 선택된 날짜 전역
  window.selectedDate = null;

  window.calendar = new FullCalendar.Calendar(calendarEl, {
    locale: "ko",
    initialView: "dayGridMonth",

    dateClick(info) {
      window.selectedDate = info.dateStr;

      // 모달 초기화 후 오픈
      if (typeof resetModalSelections === "function") resetModalSelections();
      if (typeof openAdminModal === "function") openAdminModal();
    },

    eventClick(info) {
      const ev = info.event.extendedProps;
      if (!ev) return;

      // 상세 모달 열기 함수
      if (typeof openEventDetailModal === "function") {
        openEventDetailModal(info.event);
      }
    },

    // ✅ 기존 문자열 URL → 함수로 변경 (scope 파라미터 포함)
    events: async function (fetchInfo, successCallback, failureCallback) {
      try {
        const res = await axios.get("/calendar/events", {
          params: {
            start: fetchInfo.startStr,
            end: fetchInfo.endStr,
            scope: window.currentCalendarScope, // all / mine
          },
        });
        successCallback(res.data || []);
      } catch (err) {
        console.error("❌ 일정 로딩 실패", err);
        failureCallback(err);
      }
    },
  });

  calendar.render();
  updateScopeButtons(); // 초기 버튼 상태 세팅
});
// app/static/js/calendar_core.js 맨 아래쪽에 추가

// 🔹 부서 선택 변경 시 세션에 저장 후 새로고침
document.addEventListener("DOMContentLoaded", function () {
  const deptSelect = document.getElementById("deptSelect");
  if (!deptSelect) return;

  deptSelect.addEventListener("change", async () => {
    const newDept = deptSelect.value;
    try {
      await axios.post("/calendar/set_department", { department: newDept });
      // 선택된 부서 기준으로 다시 로딩
      window.location.reload();
    } catch (err) {
      console.error("부서 변경 오류:", err);
      alert("부서 변경 중 오류가 발생했습니다.");
    }
  });
});

