(function(){
  const input = document.getElementById('files');
  const label = document.querySelector('.dropzone');
  const list = document.getElementById('file-list');
  if(input && list){
    input.addEventListener('change', () => {
      if(!input.files.length){ list.textContent = 'Aucun fichier sélectionné'; return; }
      list.textContent = Array.from(input.files).map(f => f.name).join(' · ');
    });
  }
  if(label){
    ['dragenter','dragover'].forEach(evt => label.addEventListener(evt, e => { e.preventDefault(); label.classList.add('dragover'); }));
    ['dragleave','drop'].forEach(evt => label.addEventListener(evt, e => { e.preventDefault(); label.classList.remove('dragover'); }));
  }
  document.querySelectorAll('.table-filter').forEach(filter => {
    const table = document.getElementById(filter.dataset.table);
    if(!table) return;
    filter.addEventListener('input', () => {
      const q = filter.value.toLowerCase().trim();
      table.querySelectorAll('tbody tr').forEach(row => {
        row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  });
})();
