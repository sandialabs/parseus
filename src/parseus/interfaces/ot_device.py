"""
Representation of the data that PEAT places in an Elasticsearch datastore.
"""


class OTDevice:
    """
    Takes in a dictionary glob from returned Elastic Search Data Query.
    Attempts to create a unique object from Elastic Search Data.
    """

    def __init__(self, data):
        if "host" in data:
            self.host_data = data["host"]
        else:
            self.host_data = None
        self.device_name = self.host_data
        self.full_description = self.host_data
        self.host_ip = self.host_data
        self.vendor = self.host_data
        self.brand = self.host_data
        self.model = self.host_data
        self.interface = None
        self.ssh_keys = self.host_data
        self.device_identifier = (self.full_description, self._ip)
        self.device_timestamp = data["@timestamp"]

    @property
    def ssh_keys(self):
        return self._ssh_keys

    @ssh_keys.setter
    def ssh_keys(self, data):
        if "ssh_keys" in data:
            self._ssh_keys = data["ssh_keys"]
        else:
            self._ssh_keys = None

    @property
    def device_name(self):
        return self._device_name

    @device_name.setter
    def device_name(self, host):
        if "hostname" in host:
            self._device_name = host["hostname"].strip()
        else:
            self._device_name = None

    @property
    def full_description(self):
        return self._full_description

    @full_description.setter
    def full_description(self, data):
        if "description" in data and "full" in data["description"]:
            self._full_description = data["description"]["full"].strip()
        else:
            self._full_description = None

    @property
    def host_ip(self):
        return self._ip

    @host_ip.setter
    def host_ip(self, data):
        if "ip" in data:
            self._ip = data["ip"].strip()
        else:
            self._ip = None

    @property
    def vendor(self):
        return self._vendor

    @vendor.setter
    def vendor(self, data):
        if (
            "description" in data
            and "vendor" in data["description"]
            and "id" in data["description"]["vendor"]
        ):
            self._vendor = data["description"]["vendor"]["id"].strip()
        else:
            self._vendor = None

    @property
    def brand(self):
        return self._brand

    @brand.setter
    def brand(self, data):
        if "brand" in data["description"]:
            self._brand = data["description"]["brand"].strip()
        else:
            self._brand = None

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, data):
        if "description" in data and "model" in data["description"]:
            self._model = data["description"]["model"].strip()
        else:
            self._model = None

    @property
    def device_identifier(self):
        return self._device_identifier

    @device_identifier.setter
    def device_identifier(self, data):
        self._device_identifier = data[0] + " " + data[1]

    def __str__(self) -> str:
        ret = f"HostName: {self.device_name} \n"
        ret += f"Vendor: {self.vendor} \n"
        ret += f"Brand: {self.brand} \n"
        ret += f"Model: {self.model} \n"
        ret += f"Full Description:: {self.full_description} \n"
        ret += f"IP: {self.host_ip} \n"
        ret += f"Timestamp: {self.device_timestamp}"
        return ret


def find_device(otdevice, device_set):
    for device in device_set:
        if otdevice.device_identifier == device._device_identifier:
            return device
    return None
