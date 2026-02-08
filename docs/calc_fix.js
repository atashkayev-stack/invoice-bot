// ИСПРАВЛЕННАЯ функция calcTotals - без параметров, читает всё из формы
function calcTotals() {
  // Читаем все параметры из формы
  const vatPerItem = document.getElementById("vat_per_item")?.checked || false;
  const globalVatRate = parseFloat(document.getElementById("global_vat_rate")?.value || 19);
  const discountPercentage = parseFloat(document.getElementById("discount_percentage")?.value || 0);
  const discountAmount = parseFloat(document.getElementById("discount_amount")?.value || 0);
  const shippingCost = parseFloat(document.getElementById("shipping_cost")?.value || 0);
  const shippingVatRate = parseFloat(document.getElementById("shipping_vat_rate")?.value || globalVatRate);
  
  // Определяем VAT mode
  const buyerCountry = document.getElementById("client_country")?.value || "DE";
  const buyerVatId = document.getElementById("client_vat_id")?.value || "";
  const isKlein = loadedProfile?.is_kleinunternehmer || false;
  
  const vatMode = detectVatMode({
    clientType: clientType,
    buyerCountry: buyerCountry,
    buyerVatId: buyerVatId,
    isKleinunternehmer: isKlein
  });

  // Собираем позиции
  const items = [];
  document.querySelectorAll(".item-row").forEach((row) => {
    const qty = parseFloat(row.querySelector(".item-qty")?.value || 0);
    const price = parseFloat(row.querySelector(".item-price")?.value || 0);
    const vatRate = vatPerItem 
      ? parseFloat(row.querySelector(".item-vat-rate")?.value || 0)
      : globalVatRate;
    
    items.push({
      quantity: qty,
      unit_price: price,
      vat_rate: vatRate
    });
  });

  // ЛОГИКА РАСЧЁТА (как на сервере)
  let itemsNet = 0;
  const byRate = {};

  // 1. Суммируем позиции
  items.forEach(it => {
    const lineNet = round2(it.quantity * it.unit_price);
    itemsNet += lineNet;
    
    const rate = it.vat_rate;
    if (!byRate[rate]) {
      byRate[rate] = { net: 0, vat: 0 };
    }
    byRate[rate].net += lineNet;
  });

  itemsNet = round2(itemsNet);

  // 2. Скидка
  let discount = 0;
  if (itemsNet > 0) {
    if (discountAmount > 0) {
      discount = discountAmount;
    } else if (discountPercentage > 0) {
      discount = itemsNet * (discountPercentage / 100);
    }
  }
  discount = round2(Math.min(discount, itemsNet));

  // 3. Применяем скидку пропорционально
  if (discount > 0 && itemsNet > 0) {
    const factor = (itemsNet - discount) / itemsNet;
    Object.keys(byRate).forEach(rate => {
      byRate[rate].net = round2(byRate[rate].net * factor);
    });
  }

  // 4. НДС на позиции
  Object.keys(byRate).forEach(rate => {
    const r = parseFloat(rate);
    const effectiveRate = vatMode === "standard" ? r : 0;
    byRate[rate].vat = round2(byRate[rate].net * effectiveRate / 100);
  });

  // 5. Доставка
  const shippingEffectiveRate = vatMode === "standard" ? shippingVatRate : 0;
  const shippingVat = round2(shippingCost * shippingEffectiveRate / 100);
  
  if (shippingCost > 0) {
    if (!byRate[shippingVatRate]) {
      byRate[shippingVatRate] = { net: 0, vat: 0 };
    }
    byRate[shippingVatRate].net += shippingCost;
    byRate[shippingVatRate].vat += shippingVat;
  }

  // 6. ИТОГИ
  let totalNet = 0;
  let totalVat = 0;
  
  Object.values(byRate).forEach(v => {
    totalNet += v.net;
    totalVat += v.vat;
  });

  totalNet = round2(totalNet);
  totalVat = round2(totalVat);
  const totalGross = round2(totalNet + totalVat);

  // ОБНОВЛЯЕМ ИНТЕРФЕЙС
  const netEl = document.getElementById("adv_total_net");
  const grossEl = document.getElementById("adv_total_gross");
  const breakdownEl = document.getElementById("adv_vat_breakdown_rows");

  if (netEl) netEl.textContent = fmtEUR(totalNet);
  if (grossEl) grossEl.textContent = fmtEUR(totalGross);
  
  if (breakdownEl) {
    breakdownEl.innerHTML = "";
    const rates = Object.keys(byRate).map(r => parseFloat(r)).sort((a,b) => b-a);
    rates.forEach(rate => {
      const data = byRate[rate];
      breakdownEl.insertAdjacentHTML("beforeend",
        `<div class="totals-row"><span>MwSt. ${rate}%:</span><span>${fmtEUR(data.vat)}</span></div>`
      );
    });
  }
}

function round2(x) {
  return Math.round((Number(x) + Number.EPSILON) * 100) / 100;
}

function fmtEUR(x) {
  return round2(x).toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }) + " €";
}
