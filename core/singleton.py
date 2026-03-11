def singleton(cls):
    """
     A decorator that implements the singleton pattern for a class.

     This decorator ensures that only one instance of the decorated class is created.
     Subsequent calls to create an instance will return the existing instance.

     Args:
         cls (type): The class to be decorated.

     Returns:
         function: A wrapper function that returns the single instance of the class.
     """
    instances = {}
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return get_instance
