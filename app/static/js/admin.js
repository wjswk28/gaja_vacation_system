// =====================================================
// employee_list.html 전용 관리자 기능 JS
// (관리자 지정 / 직원 삭제 / 부서 변경)
// =====================================================

// DOM 로드 후 실행
document.addEventListener("DOMContentLoaded", () => {

    // ---------------------------------------------
    // 🟦 관리자 지정 / 해제 버튼
    // ---------------------------------------------
    document.querySelectorAll(".toggle-admin-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const id = btn.dataset.userId;

            try {
                const res = await axios.post(`/toggle_admin/${id}`);

                if (res.data && res.data.status === "success") {
                    const isNowAdmin = btn.textContent.trim() === "지정"; // 현재 버튼 상태 확인

                    // 텍스트 교체
                    btn.textContent = isNowAdmin ? "해제" : "지정";

                    // 스타일 토글
                    btn.classList.toggle("bg-gray-100");
                    btn.classList.toggle("bg-gray-200");
                    btn.classList.toggle("bg-amber-300");
                    btn.classList.toggle("hover:bg-amber-400");
                    btn.classList.toggle("text-slate-600");
                    btn.classList.toggle("text-slate-800");

                    alert(res.data.message);
                } else {
                    alert(res.data.message || "처리 실패");
                }
            } catch (err) {
                alert("서버 통신 오류가 발생했습니다.");
            }
        });
    });

    // ---------------------------------------------
    // 🟥 직원 삭제 버튼
    // ---------------------------------------------
    document.querySelectorAll(".delete-employee-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const id = btn.dataset.userId;

            if (!confirm("정말 삭제하시겠습니까?")) return;

            try {
                const res = await axios.post(`/delete_employee/${id}`);

                if (res.data && res.data.status === "success") {
                    // DOM에서 행 삭제
                    const row = document.getElementById(`emp-row-${id}`);
                    if (row) row.remove();

                    alert("직원이 삭제되었습니다.");
                } else {
                    alert(res.data.message || "삭제 실패");
                }
            } catch (err) {
                alert("서버 통신 오류가 발생했습니다.");
            }
        });
    });

    // ---------------------------------------------
    // 🟦 부서 선택 (총관리자 전용)
    // ---------------------------------------------
    const deptSelect = document.getElementById("deptSelect");

    if (deptSelect) {
        deptSelect.addEventListener("change", () => {
            const selected = deptSelect.value;
            window.location.href = `/employee_list?dept=${encodeURIComponent(selected)}`;
        });
    }
});
