import math

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula a distância do grande círculo (em km) entre dois pontos na Terra
    usando a fórmula de Haversine.
    
    Isso permite ao backend calcular a proximidade em memória sem
    revelar as coordenadas geográficas exatas do locador ao locatário.
    """
    R = 6371.0  # Raio da Terra em km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return round(R * c, 2)
