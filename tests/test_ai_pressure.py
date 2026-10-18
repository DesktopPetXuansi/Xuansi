"""调度压力恢复采用不同边界，交互仍维持正常帧率。"""

from types import SimpleNamespace

from pet.app import DesktopPet
from pet.config import Settings


def test_pressure_throttles_observation_and_recovers_without_oscillation():
    intervals = []
    clock = SimpleNamespace(interval=lambda: intervals[-1] if intervals else 33,
                            setInterval=intervals.append)
    pet = SimpleNamespace(pressure=False, busy=False, settings=Settings(interval=20),
                          gate=SimpleNamespace(interval=20), avatar=SimpleNamespace(render_clock=clock))
    DesktopPet._adjust_resource_pressure(pet, 3.5)
    assert pet.pressure and pet.gate.interval == 60 and intervals[-1] == 66
    DesktopPet._adjust_resource_pressure(pet, 4.5)
    assert pet.pressure
    pet.busy = True
    DesktopPet._adjust_resource_pressure(pet, 4.5)
    assert intervals[-1] == 33
    DesktopPet._adjust_resource_pressure(pet, 5.1)
    assert not pet.pressure and pet.gate.interval == 20
    DesktopPet._adjust_resource_pressure(pet, 4.5)
    assert not pet.pressure
