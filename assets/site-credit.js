(() => {
  const stylesheetId = "site-credit-styles";

  if (!document.getElementById(stylesheetId)) {
    const stylesheet = document.createElement("link");
    stylesheet.id = stylesheetId;
    stylesheet.rel = "stylesheet";
    stylesheet.href = "/assets/site-credit.css";
    document.head.append(stylesheet);
  }

  if (document.querySelector("[data-site-credit]")) return;

  const credit = document.createElement("section");
  credit.className = "site-credit";
  credit.dataset.siteCredit = "";
  credit.setAttribute("aria-label", "إعداد الصفحة");
  credit.innerHTML = `
    <p class="site-credit__arabic" lang="ar" dir="rtl">
      <strong>إعداد الدكتور أحمد العسيري</strong>
      الأستاذ المشارك بكلية محمد بن جابر الأنصاري — جامعة البحرين
    </p>
    <p class="site-credit__english" lang="en" dir="ltr">
      Prepared by Dr. Ahmed <strong>ALASEERI</strong><br>
      Associate Professor, Mohammed bin Jaber Al-Ansari College — University of Bahrain
    </p>
  `;
  document.body.append(credit);
})();
