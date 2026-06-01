from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Paginación por defecto del API.

    Permite override por query param ?page_size=N hasta MAX.
    """
    page_size = 200
    page_size_query_param = 'page_size'
    max_page_size = 1000
