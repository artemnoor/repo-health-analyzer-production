from car import Car

class CarController:
    def __init__(self):
        self.cars = []

    def create_car(self, make, model, year, color, mileage=0):
        car = Car(make, model, year, color, mileage)
        self.cars.append(car)
        return car

    def drive_car(self, car, miles):
        car.drive(miles)

    def paint_car(self, car, new_color):
        car.paint(new_color)

    def get_car_info(self, car):
        return str(car)

    def list_all_cars(self):
        return [str(car) for car in self.cars]

if __name__ == "__main__":
    controller = CarController()

    # Create some cars
    car1 = controller.create_car("Toyota", "Camry", 2020, "Blue")
    car2 = controller.create_car("Honda", "Civic", 2018, "Red", 15000)

    # Drive the cars
    controller.drive_car(car1, 100)
    controller.drive_car(car2, 50)

    # Paint a car
    controller.paint_car(car1, "Green")

    # Get information about a car
    print(controller.get_car_info(car1))
    print(controller.get_car_info(car2))

    # List all cars
    for car_info in controller.list_all_cars():
        print(car_info)
