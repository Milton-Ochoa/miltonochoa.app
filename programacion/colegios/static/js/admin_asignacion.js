window.addEventListener('load', function() {
    var colegioSelect = document.getElementById('id_colegio');
    var gradoSelect = document.getElementById('id_grado');

    if (colegioSelect && gradoSelect) {
        colegioSelect.addEventListener('change', function() {
            var colegioId = this.value;
            
            // Limpiar opciones
            gradoSelect.innerHTML = '<option value="">---------</option>';

            if (colegioId) {
                fetch('/colegios/ajax/cargar-grados/?colegio_id=' + colegioId)
                    .then(response => {
                        if (!response.ok) throw new Error('Error en la red');
                        return response.json();
                    })
                    .then(data => {
                        data.forEach(function(grado) {
                            var option = document.createElement('option');
                            option.value = grado;
                            option.textContent = grado;
                            gradoSelect.appendChild(option);
                        });
                    })
                    .catch(error => console.error('Error cargando grados:', error));
            }
        });
    }
});