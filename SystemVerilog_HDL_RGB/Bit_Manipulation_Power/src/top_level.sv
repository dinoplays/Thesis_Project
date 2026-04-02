module top_level (
	input  wire         CLOCK_50,
	input  logic [23:0] PIXEL_BIT_DATA,
	input  wire         PIXEL_VALID_IN,
	input  wire         SOC_IN,
	input  wire         EOC_IN,
	input  wire         SOLF_IN,
	input  wire         EOLF_IN,

	output logic        SOLF_OUT,
	output logic        EOLF_OUT,
	output logic [5:0]  ROW_IDX_OUT,
	output logic [5:0]  COLUMN_IDX_OUT,
	output logic        PIXEL_VALID_OUT,
	output logic [14:0] CONFIDENCE_PIXEL_BIT_DATA,
	output logic [23:0] DISPARITY_PIXEL_BIT_DATA
);

	parameter int unsigned IMAGE_DIM    = 64;
	parameter int unsigned IMAGE_DIM_BS = 6;

	localparam int unsigned RAM_ADDR_W = (IMAGE_DIM_BS << 1) + 2;

	logic [7:0] pixel_in_red;
	logic [7:0] pixel_in_green;
	logic [7:0] pixel_in_blue;

	assign pixel_in_red   = PIXEL_BIT_DATA[23:16];
	assign pixel_in_green = PIXEL_BIT_DATA[15:8];
	assign pixel_in_blue  = PIXEL_BIT_DATA[7:0];

	logic soc_filtered_out_red;
	logic eoc_filtered_out_red;
	logic solf_filtered_out_red;
	logic eolf_filtered_out_red;
	logic filtered_pixel_valid_red;

	logic soc_filtered_out_green;
	logic eoc_filtered_out_green;
	logic solf_filtered_out_green;
	logic eolf_filtered_out_green;
	logic filtered_pixel_valid_green;

	logic soc_filtered_out_blue;
	logic eoc_filtered_out_blue;
	logic solf_filtered_out_blue;
	logic eolf_filtered_out_blue;
	logic filtered_pixel_valid_blue;

	logic [14:0] filtered_pixel_red;
	logic [14:0] filtered_pixel_green;
	logic [14:0] filtered_pixel_blue;

	bit_shift_low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) BSLPF_RED (
		.clk(CLOCK_50),
		.pixel_valid_in(PIXEL_VALID_IN),
		.soc_in(SOC_IN),
		.eoc_in(EOC_IN),
		.solf_in(SOLF_IN),
		.eolf_in(EOLF_IN),
		.pixel_in(pixel_in_red),
		.pixel_valid_out(filtered_pixel_valid_red),
		.soc_out(soc_filtered_out_red),
		.eoc_out(eoc_filtered_out_red),
		.solf_out(solf_filtered_out_red),
		.eolf_out(eolf_filtered_out_red),
		.pixel_out(filtered_pixel_red)
	);

	bit_shift_low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) BSLPF_GREEN (
		.clk(CLOCK_50),
		.pixel_valid_in(PIXEL_VALID_IN),
		.soc_in(SOC_IN),
		.eoc_in(EOC_IN),
		.solf_in(SOLF_IN),
		.eolf_in(EOLF_IN),
		.pixel_in(pixel_in_green),
		.pixel_valid_out(filtered_pixel_valid_green),
		.soc_out(soc_filtered_out_green),
		.eoc_out(eoc_filtered_out_green),
		.solf_out(solf_filtered_out_green),
		.eolf_out(eolf_filtered_out_green),
		.pixel_out(filtered_pixel_green)
	);

	bit_shift_low_pass_filter #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) BSLPF_BLUE (
		.clk(CLOCK_50),
		.pixel_valid_in(PIXEL_VALID_IN),
		.soc_in(SOC_IN),
		.eoc_in(EOC_IN),
		.solf_in(SOLF_IN),
		.eolf_in(EOLF_IN),
		.pixel_in(pixel_in_blue),
		.pixel_valid_out(filtered_pixel_valid_blue),
		.soc_out(soc_filtered_out_blue),
		.eoc_out(eoc_filtered_out_blue),
		.solf_out(solf_filtered_out_blue),
		.eolf_out(eolf_filtered_out_blue),
		.pixel_out(filtered_pixel_blue)
	);

	logic soc_epi_in;
	logic eoc_epi_in;
	logic solf_epi_in;
	logic eolf_epi_in;
	logic pixel_valid_epi_in;

	logic [14:0] pixel_red_epi_in;
	logic [14:0] pixel_green_epi_in;
	logic [14:0] pixel_blue_epi_in;

	always_ff @(posedge CLOCK_50) begin
		soc_epi_in         <= soc_filtered_out_red;
		eoc_epi_in         <= eoc_filtered_out_red;
		solf_epi_in        <= solf_filtered_out_red;
		eolf_epi_in        <= eolf_filtered_out_red;
		pixel_valid_epi_in <= filtered_pixel_valid_red;

		pixel_red_epi_in   <= filtered_pixel_red;
		pixel_green_epi_in <= filtered_pixel_green;
		pixel_blue_epi_in  <= filtered_pixel_blue;
	end

	logic                           epic_storage_we_red [0:11];
	logic                           epic_storage_we_8v_red;
	logic [RAM_ADDR_W-1:0]          epic_storage_wr_addr_red [0:11];
	logic [RAM_ADDR_W-1:0]          epic_storage_wr_addr_8v_red;
	logic [14:0]                    epic_storage_wr_data_red;
	logic [RAM_ADDR_W-1:0]          epic_storage_rd_addr_red;
	logic [14:0]                    epic_storage_rd_data_red [0:11];
	logic [14:0]                    epic_storage_rd_data_8v_red;
	logic                           epic_shared_banks_5_to_8_released_red;
	logic                           epic_shared_banks_5_to_8_epi_read_active_red;

	logic                           epic_storage_we_green [0:11];
	logic                           epic_storage_we_8v_green;
	logic [RAM_ADDR_W-1:0]          epic_storage_wr_addr_green [0:11];
	logic [RAM_ADDR_W-1:0]          epic_storage_wr_addr_8v_green;
	logic [14:0]                    epic_storage_wr_data_green;
	logic [RAM_ADDR_W-1:0]          epic_storage_rd_addr_green;
	logic [14:0]                    epic_storage_rd_data_green [0:11];
	logic [14:0]                    epic_storage_rd_data_8v_green;
	logic                           epic_shared_banks_5_to_8_released_green;
	logic                           epic_shared_banks_5_to_8_epi_read_active_green;

	logic                           epic_storage_we_blue [0:11];
	logic                           epic_storage_we_8v_blue;
	logic [RAM_ADDR_W-1:0]          epic_storage_wr_addr_blue [0:11];
	logic [RAM_ADDR_W-1:0]          epic_storage_wr_addr_8v_blue;
	logic [14:0]                    epic_storage_wr_data_blue;
	logic [RAM_ADDR_W-1:0]          epic_storage_rd_addr_blue;
	logic [14:0]                    epic_storage_rd_data_blue [0:11];
	logic [14:0]                    epic_storage_rd_data_8v_blue;
	logic                           epic_shared_banks_5_to_8_released_blue;
	logic                           epic_shared_banks_5_to_8_epi_read_active_blue;

	logic                           fao_shared_we [0:11];
	logic [((IMAGE_DIM_BS << 1) - 1):0] fao_shared_wr_addr [0:11];
	logic [14:0]                    fao_shared_wr_data [0:11];
	logic [((IMAGE_DIM_BS << 1) - 1):0] fao_shared_rd_addr [0:11];
	logic [14:0]                    fao_shared_rd_data [0:11];

	logic                           fao_shared_we_red [0:3];
	logic                           fao_shared_we_green [0:3];
	logic                           fao_shared_we_blue [0:3];

	logic [RAM_ADDR_W-1:0]          fao_shared_wr_addr_red [0:3];
	logic [RAM_ADDR_W-1:0]          fao_shared_wr_addr_green [0:3];
	logic [RAM_ADDR_W-1:0]          fao_shared_wr_addr_blue [0:3];

	logic [14:0]                    fao_shared_wr_data_red [0:3];
	logic [14:0]                    fao_shared_wr_data_green [0:3];
	logic [14:0]                    fao_shared_wr_data_blue [0:3];

	logic [RAM_ADDR_W-1:0]          fao_shared_rd_addr_red [0:3];
	logic [RAM_ADDR_W-1:0]          fao_shared_rd_addr_green [0:3];
	logic [RAM_ADDR_W-1:0]          fao_shared_rd_addr_blue [0:3];

	logic [14:0]                    fao_shared_rd_data_red [0:3];
	logic [14:0]                    fao_shared_rd_data_green [0:3];
	logic [14:0]                    fao_shared_rd_data_blue [0:3];

	integer i;

	always_comb begin
		for (i = 0; i < 4; i = i + 1) begin
			fao_shared_we_red[i]   = fao_shared_we[i];
			fao_shared_we_green[i] = fao_shared_we[i + 4];
			fao_shared_we_blue[i]  = fao_shared_we[i + 8];

			fao_shared_wr_addr_red[i]   = {{(RAM_ADDR_W - (IMAGE_DIM_BS << 1)){1'b0}}, fao_shared_wr_addr[i]};
			fao_shared_wr_addr_green[i] = {{(RAM_ADDR_W - (IMAGE_DIM_BS << 1)){1'b0}}, fao_shared_wr_addr[i + 4]};
			fao_shared_wr_addr_blue[i]  = {{(RAM_ADDR_W - (IMAGE_DIM_BS << 1)){1'b0}}, fao_shared_wr_addr[i + 8]};

			fao_shared_wr_data_red[i]   = fao_shared_wr_data[i];
			fao_shared_wr_data_green[i] = fao_shared_wr_data[i + 4];
			fao_shared_wr_data_blue[i]  = fao_shared_wr_data[i + 8];

			fao_shared_rd_addr_red[i]   = {{(RAM_ADDR_W - (IMAGE_DIM_BS << 1)){1'b0}}, fao_shared_rd_addr[i]};
			fao_shared_rd_addr_green[i] = {{(RAM_ADDR_W - (IMAGE_DIM_BS << 1)){1'b0}}, fao_shared_rd_addr[i + 4]};
			fao_shared_rd_addr_blue[i]  = {{(RAM_ADDR_W - (IMAGE_DIM_BS << 1)){1'b0}}, fao_shared_rd_addr[i + 8]};

			fao_shared_rd_data[i]     = fao_shared_rd_data_red[i];
			fao_shared_rd_data[i + 4] = fao_shared_rd_data_green[i];
			fao_shared_rd_data[i + 8] = fao_shared_rd_data_blue[i];
		end
	end

	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS),
		.RAM_ADDR_W(RAM_ADDR_W)
	) SHARED_RED (
		.clk(CLOCK_50),
		.takeover_banks_5_to_8(epic_shared_banks_5_to_8_released_red),
		.epi_read_banks_5_to_8_active(epic_shared_banks_5_to_8_epi_read_active_red),
		.epi_we(epic_storage_we_red),
		.epi_we_8v(epic_storage_we_8v_red),
		.epi_wr_addr(epic_storage_wr_addr_red),
		.epi_wr_addr_8v(epic_storage_wr_addr_8v_red),
		.epi_wr_data(epic_storage_wr_data_red),
		.epi_rd_addr(epic_storage_rd_addr_red),
		.epi_rd_data(epic_storage_rd_data_red),
		.epi_rd_data_8v(epic_storage_rd_data_8v_red),
		.fao_we(fao_shared_we_red),
		.fao_wr_addr(fao_shared_wr_addr_red),
		.fao_wr_data(fao_shared_wr_data_red),
		.fao_rd_addr(fao_shared_rd_addr_red),
		.fao_rd_data(fao_shared_rd_data_red)
	);

	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS),
		.RAM_ADDR_W(RAM_ADDR_W)
	) SHARED_GREEN (
		.clk(CLOCK_50),
		.takeover_banks_5_to_8(epic_shared_banks_5_to_8_released_green),
		.epi_read_banks_5_to_8_active(epic_shared_banks_5_to_8_epi_read_active_green),
		.epi_we(epic_storage_we_green),
		.epi_we_8v(epic_storage_we_8v_green),
		.epi_wr_addr(epic_storage_wr_addr_green),
		.epi_wr_addr_8v(epic_storage_wr_addr_8v_green),
		.epi_wr_data(epic_storage_wr_data_green),
		.epi_rd_addr(epic_storage_rd_addr_green),
		.epi_rd_data(epic_storage_rd_data_green),
		.epi_rd_data_8v(epic_storage_rd_data_8v_green),
		.fao_we(fao_shared_we_green),
		.fao_wr_addr(fao_shared_wr_addr_green),
		.fao_wr_data(fao_shared_wr_data_green),
		.fao_rd_addr(fao_shared_rd_addr_green),
		.fao_rd_data(fao_shared_rd_data_green)
	);

	shared_frame_storage #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS),
		.RAM_ADDR_W(RAM_ADDR_W)
	) SHARED_BLUE (
		.clk(CLOCK_50),
		.takeover_banks_5_to_8(epic_shared_banks_5_to_8_released_blue),
		.epi_read_banks_5_to_8_active(epic_shared_banks_5_to_8_epi_read_active_blue),
		.epi_we(epic_storage_we_blue),
		.epi_we_8v(epic_storage_we_8v_blue),
		.epi_wr_addr(epic_storage_wr_addr_blue),
		.epi_wr_addr_8v(epic_storage_wr_addr_8v_blue),
		.epi_wr_data(epic_storage_wr_data_blue),
		.epi_rd_addr(epic_storage_rd_addr_blue),
		.epi_rd_data(epic_storage_rd_data_blue),
		.epi_rd_data_8v(epic_storage_rd_data_8v_blue),
		.fao_we(fao_shared_we_blue),
		.fao_wr_addr(fao_shared_wr_addr_blue),
		.fao_wr_data(fao_shared_wr_data_blue),
		.fao_rd_addr(fao_shared_rd_addr_blue),
		.fao_rd_data(fao_shared_rd_data_blue)
	);

	logic                    epi_valid_out_red;
	logic                    epi_valid_out_green;
	logic                    epi_valid_out_blue;

	logic                    epi_orientation_out_red;
	logic                    epi_orientation_out_green;
	logic                    epi_orientation_out_blue;

	logic [14:0]             epi_column_out_red [0:8];
	logic [14:0]             epi_column_out_green [0:8];
	logic [14:0]             epi_column_out_blue [0:8];

	logic [IMAGE_DIM_BS-1:0] epi_column_idx_out_red;
	logic [IMAGE_DIM_BS-1:0] epi_column_idx_out_green;
	logic [IMAGE_DIM_BS-1:0] epi_column_idx_out_blue;

	logic [IMAGE_DIM_BS-1:0] epi_idx_out_red;
	logic [IMAGE_DIM_BS-1:0] epi_idx_out_green;
	logic [IMAGE_DIM_BS-1:0] epi_idx_out_blue;

	epi_compiler #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS),
		.RAM_ADDR_W(RAM_ADDR_W),
		.RAM_COLOUR_OFFSET('0)
	) EPIC_RED (
		.clk(CLOCK_50),
		.pixel_valid_in(pixel_valid_epi_in),
		.soc_in(soc_epi_in),
		.eoc_in(eoc_epi_in),
		.solf_in(solf_epi_in),
		.eolf_in(eolf_epi_in),
		.pixel_in(pixel_red_epi_in),
		.storage_we(epic_storage_we_red),
		.storage_we_8v(epic_storage_we_8v_red),
		.storage_wr_addr(epic_storage_wr_addr_red),
		.storage_wr_addr_8v(epic_storage_wr_addr_8v_red),
		.storage_wr_data(epic_storage_wr_data_red),
		.storage_rd_addr(epic_storage_rd_addr_red),
		.storage_rd_data(epic_storage_rd_data_red),
		.storage_rd_data_8v(epic_storage_rd_data_8v_red),
		.shared_banks_5_to_8_released(epic_shared_banks_5_to_8_released_red),
		.shared_banks_5_to_8_epi_read_active(epic_shared_banks_5_to_8_epi_read_active_red),
		.epi_valid_out(epi_valid_out_red),
		.epi_column_out(epi_column_out_red),
		.epi_column_idx_out(epi_column_idx_out_red),
		.epi_idx_out(epi_idx_out_red),
		.orientation_out(epi_orientation_out_red)
	);

	epi_compiler #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS),
		.RAM_ADDR_W(RAM_ADDR_W),
		.RAM_COLOUR_OFFSET('0)
	) EPIC_GREEN (
		.clk(CLOCK_50),
		.pixel_valid_in(pixel_valid_epi_in),
		.soc_in(soc_epi_in),
		.eoc_in(eoc_epi_in),
		.solf_in(solf_epi_in),
		.eolf_in(eolf_epi_in),
		.pixel_in(pixel_green_epi_in),
		.storage_we(epic_storage_we_green),
		.storage_we_8v(epic_storage_we_8v_green),
		.storage_wr_addr(epic_storage_wr_addr_green),
		.storage_wr_addr_8v(epic_storage_wr_addr_8v_green),
		.storage_wr_data(epic_storage_wr_data_green),
		.storage_rd_addr(epic_storage_rd_addr_green),
		.storage_rd_data(epic_storage_rd_data_green),
		.storage_rd_data_8v(epic_storage_rd_data_8v_green),
		.shared_banks_5_to_8_released(epic_shared_banks_5_to_8_released_green),
		.shared_banks_5_to_8_epi_read_active(epic_shared_banks_5_to_8_epi_read_active_green),
		.epi_valid_out(epi_valid_out_green),
		.epi_column_out(epi_column_out_green),
		.epi_column_idx_out(epi_column_idx_out_green),
		.epi_idx_out(epi_idx_out_green),
		.orientation_out(epi_orientation_out_green)
	);

	epi_compiler #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS),
		.RAM_ADDR_W(RAM_ADDR_W),
		.RAM_COLOUR_OFFSET('0)
	) EPIC_BLUE (
		.clk(CLOCK_50),
		.pixel_valid_in(pixel_valid_epi_in),
		.soc_in(soc_epi_in),
		.eoc_in(eoc_epi_in),
		.solf_in(solf_epi_in),
		.eolf_in(eolf_epi_in),
		.pixel_in(pixel_blue_epi_in),
		.storage_we(epic_storage_we_blue),
		.storage_we_8v(epic_storage_we_8v_blue),
		.storage_wr_addr(epic_storage_wr_addr_blue),
		.storage_wr_addr_8v(epic_storage_wr_addr_8v_blue),
		.storage_wr_data(epic_storage_wr_data_blue),
		.storage_rd_addr(epic_storage_rd_addr_blue),
		.storage_rd_data(epic_storage_rd_data_blue),
		.storage_rd_data_8v(epic_storage_rd_data_8v_blue),
		.shared_banks_5_to_8_released(epic_shared_banks_5_to_8_released_blue),
		.shared_banks_5_to_8_epi_read_active(epic_shared_banks_5_to_8_epi_read_active_blue),
		.epi_valid_out(epi_valid_out_blue),
		.epi_column_out(epi_column_out_blue),
		.epi_column_idx_out(epi_column_idx_out_blue),
		.epi_idx_out(epi_idx_out_blue),
		.orientation_out(epi_orientation_out_blue)
	);

	logic                    epi_valid_out;
	logic                    epi_orientation_out;
	logic [IMAGE_DIM_BS-1:0] epi_column_idx_out;
	logic [IMAGE_DIM_BS-1:0] epi_idx_out;

	always_comb begin
		epi_valid_out       = epi_valid_out_red;
		epi_orientation_out = epi_orientation_out_red;
		epi_column_idx_out  = epi_column_idx_out_red;
		epi_idx_out         = epi_idx_out_red;
	end

	logic                    epi_valid_in;
	logic [14:0]             epi_column_in_red [0:8];
	logic [14:0]             epi_column_in_green [0:8];
	logic [14:0]             epi_column_in_blue [0:8];
	logic [IMAGE_DIM_BS-1:0] epi_column_idx_in;
	logic [IMAGE_DIM_BS-1:0] epi_idx_in;
	logic                    epi_orientation_in;

	always_ff @(posedge CLOCK_50) begin
		epi_valid_in        <= epi_valid_out;
		epi_column_in_red   <= epi_column_out_red;
		epi_column_in_green <= epi_column_out_green;
		epi_column_in_blue  <= epi_column_out_blue;
		epi_column_idx_in   <= epi_column_idx_out;
		epi_idx_in          <= epi_idx_out;
		epi_orientation_in  <= epi_orientation_out;
	end

	logic                            angular_derivative_valid_out_red;
	logic                            angular_derivative_valid_out_green;
	logic                            angular_derivative_valid_out_blue;

	logic signed [15:0]              angular_derivative_column_out_red [0:6];
	logic signed [15:0]              angular_derivative_column_out_green [0:6];
	logic signed [15:0]              angular_derivative_column_out_blue [0:6];

	logic [IMAGE_DIM_BS-1:0]         angular_derivative_row_idx_out_red;
	logic [IMAGE_DIM_BS-1:0]         angular_derivative_column_idx_out_red;
	logic                            derivative_orientation_out_red;

	logic [IMAGE_DIM_BS-1:0]         angular_derivative_row_idx_out_green;
	logic [IMAGE_DIM_BS-1:0]         angular_derivative_column_idx_out_green;
	logic                            derivative_orientation_out_green;

	logic [IMAGE_DIM_BS-1:0]         angular_derivative_row_idx_out_blue;
	logic [IMAGE_DIM_BS-1:0]         angular_derivative_column_idx_out_blue;
	logic                            derivative_orientation_out_blue;

	logic                            confidence_valid_out_red;
	logic                            confidence_valid_out_green;
	logic                            confidence_valid_out_blue;

	logic [14:0]                     confidence_pixel_out_red;
	logic [14:0]                     confidence_pixel_out_green;
	logic [14:0]                     confidence_pixel_out_blue;

	logic [IMAGE_DIM_BS-1:0]         confidence_row_idx_out_red;
	logic [IMAGE_DIM_BS-1:0]         confidence_column_idx_out_red;
	logic                            confidence_orientation_out_red;

	logic [IMAGE_DIM_BS-1:0]         confidence_row_idx_out_green;
	logic [IMAGE_DIM_BS-1:0]         confidence_column_idx_out_green;
	logic                            confidence_orientation_out_green;

	logic [IMAGE_DIM_BS-1:0]         confidence_row_idx_out_blue;
	logic [IMAGE_DIM_BS-1:0]         confidence_column_idx_out_blue;
	logic                            confidence_orientation_out_blue;

	confidence_computer #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) CONF_COMP_RED (
		.clk(CLOCK_50),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in_red),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.orientation_in(epi_orientation_in),
		.derivative_valid_out(angular_derivative_valid_out_red),
		.derivative_column_out(angular_derivative_column_out_red),
		.derivative_row_idx_out(angular_derivative_row_idx_out_red),
		.derivative_column_idx_out(angular_derivative_column_idx_out_red),
		.derivative_orientation_out(derivative_orientation_out_red),
		.confidence_valid_out(confidence_valid_out_red),
		.confidence_pixel_out(confidence_pixel_out_red),
		.confidence_row_idx_out(confidence_row_idx_out_red),
		.confidence_column_idx_out(confidence_column_idx_out_red),
		.confidence_orientation_out(confidence_orientation_out_red)
	);

	confidence_computer #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) CONF_COMP_GREEN (
		.clk(CLOCK_50),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in_green),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.orientation_in(epi_orientation_in),
		.derivative_valid_out(angular_derivative_valid_out_green),
		.derivative_column_out(angular_derivative_column_out_green),
		.derivative_row_idx_out(angular_derivative_row_idx_out_green),
		.derivative_column_idx_out(angular_derivative_column_idx_out_green),
		.derivative_orientation_out(derivative_orientation_out_green),
		.confidence_valid_out(confidence_valid_out_green),
		.confidence_pixel_out(confidence_pixel_out_green),
		.confidence_row_idx_out(confidence_row_idx_out_green),
		.confidence_column_idx_out(confidence_column_idx_out_green),
		.confidence_orientation_out(confidence_orientation_out_green)
	);

	confidence_computer #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) CONF_COMP_BLUE (
		.clk(CLOCK_50),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in_blue),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.orientation_in(epi_orientation_in),
		.derivative_valid_out(angular_derivative_valid_out_blue),
		.derivative_column_out(angular_derivative_column_out_blue),
		.derivative_row_idx_out(angular_derivative_row_idx_out_blue),
		.derivative_column_idx_out(angular_derivative_column_idx_out_blue),
		.derivative_orientation_out(derivative_orientation_out_blue),
		.confidence_valid_out(confidence_valid_out_blue),
		.confidence_pixel_out(confidence_pixel_out_blue),
		.confidence_row_idx_out(confidence_row_idx_out_blue),
		.confidence_column_idx_out(confidence_column_idx_out_blue),
		.confidence_orientation_out(confidence_orientation_out_blue)
	);

	logic                    confidence_valid_out;
	logic [IMAGE_DIM_BS-1:0] confidence_row_idx_out;
	logic [IMAGE_DIM_BS-1:0] confidence_column_idx_out;
	logic                    confidence_orientation_out;

	always_comb begin
		confidence_valid_out       = confidence_valid_out_red;
		confidence_row_idx_out     = confidence_row_idx_out_red;
		confidence_column_idx_out  = confidence_column_idx_out_red;
		confidence_orientation_out = confidence_orientation_out_red;
	end

	logic                            disparity_valid_out_red;
	logic                            disparity_valid_out_green;
	logic                            disparity_valid_out_blue;

	logic                            disparity_orientation_out_red;
	logic                            disparity_orientation_out_green;
	logic                            disparity_orientation_out_blue;

	logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out_red;
	logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out_red;
	logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out_green;
	logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out_green;
	logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out_blue;
	logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out_blue;

	logic [31:0]                     disparity_pixel_out_red;
	logic [31:0]                     disparity_pixel_out_green;
	logic [31:0]                     disparity_pixel_out_blue;

	disparity_estimator #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DISP_EST_RED (
		.clk(CLOCK_50),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in_red),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.epi_orientation_in(epi_orientation_in),
		.angular_derivative_valid_in(angular_derivative_valid_out_red),
		.angular_derivative_column_in(angular_derivative_column_out_red),
		.angular_derivative_row_idx_in(angular_derivative_row_idx_out_red),
		.angular_derivative_column_idx_in(angular_derivative_column_idx_out_red),
		.angular_derivative_orientation_in(derivative_orientation_out_red),
		.disparity_valid_out(disparity_valid_out_red),
		.disparity_pixel_out(disparity_pixel_out_red),
		.disparity_row_idx_out(disparity_row_idx_out_red),
		.disparity_column_idx_out(disparity_column_idx_out_red),
		.orientation_out(disparity_orientation_out_red)
	);

	disparity_estimator #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DISP_EST_GREEN (
		.clk(CLOCK_50),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in_green),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.epi_orientation_in(epi_orientation_in),
		.angular_derivative_valid_in(angular_derivative_valid_out_green),
		.angular_derivative_column_in(angular_derivative_column_out_green),
		.angular_derivative_row_idx_in(angular_derivative_row_idx_out_green),
		.angular_derivative_column_idx_in(angular_derivative_column_idx_out_green),
		.angular_derivative_orientation_in(derivative_orientation_out_green),
		.disparity_valid_out(disparity_valid_out_green),
		.disparity_pixel_out(disparity_pixel_out_green),
		.disparity_row_idx_out(disparity_row_idx_out_green),
		.disparity_column_idx_out(disparity_column_idx_out_green),
		.orientation_out(disparity_orientation_out_green)
	);

	disparity_estimator #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) DISP_EST_BLUE (
		.clk(CLOCK_50),
		.epi_valid_in(epi_valid_in),
		.epi_column_in(epi_column_in_blue),
		.epi_column_idx_in(epi_column_idx_in),
		.epi_idx_in(epi_idx_in),
		.epi_orientation_in(epi_orientation_in),
		.angular_derivative_valid_in(angular_derivative_valid_out_blue),
		.angular_derivative_column_in(angular_derivative_column_out_blue),
		.angular_derivative_row_idx_in(angular_derivative_row_idx_out_blue),
		.angular_derivative_column_idx_in(angular_derivative_column_idx_out_blue),
		.angular_derivative_orientation_in(derivative_orientation_out_blue),
		.disparity_valid_out(disparity_valid_out_blue),
		.disparity_pixel_out(disparity_pixel_out_blue),
		.disparity_row_idx_out(disparity_row_idx_out_blue),
		.disparity_column_idx_out(disparity_column_idx_out_blue),
		.orientation_out(disparity_orientation_out_blue)
	);

	logic                    disparity_valid_out;
	logic                    disparity_orientation_out;
	logic [IMAGE_DIM_BS-1:0] disparity_row_idx_out;
	logic [IMAGE_DIM_BS-1:0] disparity_column_idx_out;

	always_comb begin
		disparity_valid_out       = disparity_valid_out_red;
		disparity_orientation_out = disparity_orientation_out_red;
		disparity_row_idx_out     = disparity_row_idx_out_red;
		disparity_column_idx_out  = disparity_column_idx_out_red;
	end

	fused_aligned_output #(
		.IMAGE_DIM(IMAGE_DIM),
		.IMAGE_DIM_BS(IMAGE_DIM_BS)
	) FAO_RGB (
		.clk(CLOCK_50),
		.confidence_valid_in(confidence_valid_out),
		.confidence_pixel_in_red(confidence_pixel_out_red),
		.confidence_pixel_in_green(confidence_pixel_out_green),
		.confidence_pixel_in_blue(confidence_pixel_out_blue),
		.confidence_row_idx_in(confidence_row_idx_out),
		.confidence_column_idx_in(confidence_column_idx_out),
		.confidence_orientation_in(confidence_orientation_out),
		.disparity_valid_in(disparity_valid_out),
		.disparity_pixel_in_red(disparity_pixel_out_red),
		.disparity_pixel_in_green(disparity_pixel_out_green),
		.disparity_pixel_in_blue(disparity_pixel_out_blue),
		.disparity_row_idx_in(disparity_row_idx_out),
		.disparity_column_idx_in(disparity_column_idx_out),
		.disparity_orientation_in(disparity_orientation_out),
		.shared_banks_available(epic_shared_banks_5_to_8_released_red),
		.shared_we(fao_shared_we),
		.shared_wr_addr(fao_shared_wr_addr),
		.shared_wr_data(fao_shared_wr_data),
		.shared_rd_addr(fao_shared_rd_addr),
		.shared_rd_data(fao_shared_rd_data),
		.solf_out(SOLF_OUT),
		.eolf_out(EOLF_OUT),
		.pixel_valid_out(PIXEL_VALID_OUT),
		.row_idx_out(ROW_IDX_OUT),
		.column_idx_out(COLUMN_IDX_OUT),
		.confidence_pixel_bit_data(CONFIDENCE_PIXEL_BIT_DATA),
		.weighted_disparity_pixel_bit_data(DISPARITY_PIXEL_BIT_DATA)
	);

endmodule