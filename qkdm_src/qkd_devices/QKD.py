import abc

class QKD(abc.ABC):
	@abc.abstractmethod
	def __init__(self, role:str, port:int, address:str, max_key_count:int, dimension:int) : 
		pass 

	@abc.abstractmethod
	def begin(self) -> int:
		pass

	@abc.abstractmethod
	def exchangeKey(self) -> tuple[bytes, int]:
		pass

	@abc.abstractmethod
	def end(self):
		pass
