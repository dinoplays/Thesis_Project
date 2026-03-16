module epi_compiler #(
	parameter int unsigned IMAGE_DIM    = 128,
	parameter int unsigned IMAGE_DIM_BS = 7
)(
	input  wire                                   clk,
	input  wire                                   pixel_valid_in,
	input  wire                                   soc_in,
	input  wire                                   eoc_in,
	input  wire                                   solf_in,
	input  wire                                   eolf_in,
	input  wire [14:0]                            pixel_in,

	// ---------------------------------------------------------------------
	// Shared storage interface
	// ---------------------------------------------------------------------
	output logic                                  storage_we [0:11],
	output logic                                  storage_we_8v,
	output logic [((2*IMAGE_DIM_BS)-1):0]        storage_wr_addr [0:11],
	output logic [((2*IMAGE_DIM_BS)-1):0]        storage_wr_addr_8v,
	output logic [14:0]                           storage_wr_data,
	output logic [((2*IMAGE_DIM_BS)-1):0]        storage_rd_addr,
	input  wire [14:0]                            storage_rd_data [0:11],
	input  wire [14:0]                            storage_rd_data_8v,
	output logic                                  shared_banks_5_to_8_released,

	output logic                                  epi_valid_out,
	output logic [14:0]                           epi_column_out [0:8],
	output logic [IMAGE_DIM_BS-1:0]              epi_column_idx_out,
	output logic [IMAGE_DIM_BS-1:0]              epi_idx_out,
	output logic                                  orientation_out
);

	localparam int unsigned EPI_FRAME_PTR_W = 2 * IMAGE_DIM_BS;

	localparam logic [4:0] H_READ_CAPTURE = 5'd12;
	localparam logic [4:0] V_READ_CAPTURE = 5'd16;

	logic                                   in_lf_flag       = 1'b0;
	logic [4:0]                             capture_in_count = 5'd0;
	logic [IMAGE_DIM_BS-1:0]                row_in_count     = '0;
	logic [IMAGE_DIM_BS-1:0]                column_in_count  = '0;

	logic h_read_phase;
	logic h_read_phase_d;
	logic write_phase;
	logic v08_store_phase;

	assign h_read_phase  = (in_lf_flag || solf_in) &&
	                       pixel_valid_in &&
	                       (capture_in_count == H_READ_CAPTURE);

	assign write_phase   = (in_lf_flag || solf_in) &&
	                       pixel_valid_in &&
	                       (capture_in_count != H_READ_CAPTURE) &&
	                       (capture_in_count != V_READ_CAPTURE);

	assign v08_store_phase = (in_lf_flag || solf_in) &&
	                         pixel_valid_in &&
	                         (capture_in_count == V_READ_CAPTURE);

	logic [14:0]                     pixel_in_d         = '0;
	logic [IMAGE_DIM_BS-1:0]         row_in_count_d     = '0;
	logic [IMAGE_DIM_BS-1:0]         column_in_count_d  = '0;

	function automatic [EPI_FRAME_PTR_W-1:0] addr_row_major(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_row_major =
				({{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, row_i} << IMAGE_DIM_BS) +
				{{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, col_i};
		end
	endfunction

	function automatic [EPI_FRAME_PTR_W-1:0] addr_transposed(
		input logic [IMAGE_DIM_BS-1:0] row_i,
		input logic [IMAGE_DIM_BS-1:0] col_i
	);
		begin
			addr_transposed =
				({{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, col_i} << IMAGE_DIM_BS) +
				{{(EPI_FRAME_PTR_W-IMAGE_DIM_BS){1'b0}}, row_i};
		end
	endfunction

	function automatic logic is_vertical_store_capture(
		input logic [4:0] cap_i
	);
		begin
			case (cap_i)
				5'd0,
				5'd1,
				5'd2,
				5'd3,
				5'd13,
				5'd14,
				5'd15: is_vertical_store_capture = 1'b1;
				default: is_vertical_store_capture = 1'b0;
			endcase
		end
	endfunction

	logic [EPI_FRAME_PTR_W-1:0] wr_addr_row_major;
	logic [EPI_FRAME_PTR_W-1:0] wr_addr_transposed;
	logic [EPI_FRAME_PTR_W-1:0] wr_addr_calc;
	logic [EPI_FRAME_PTR_W-1:0] wr_addr_frame4;

	assign wr_addr_row_major  = addr_row_major(row_in_count, column_in_count);
	assign wr_addr_transposed = addr_transposed(row_in_count, column_in_count);
	assign wr_addr_calc       = is_vertical_store_capture(capture_in_count) ? wr_addr_transposed
	                                                                        : wr_addr_row_major;
	assign wr_addr_frame4     = v08_store_phase ? wr_addr_transposed : wr_addr_calc;

	logic vertical_output_pending = 1'b0;
	logic vertical_output_active  = 1'b0;

	logic [IMAGE_DIM_BS-1:0] v_epi_idx     = '0;
	logic [IMAGE_DIM_BS-1:0] v_spatial_idx = '0;

	logic                    v_read_issue_d    = 1'b0;
	logic [IMAGE_DIM_BS-1:0] v_epi_idx_d       = '0;
	logic [IMAGE_DIM_BS-1:0] v_spatial_idx_d   = '0;

	logic [EPI_FRAME_PTR_W-1:0] rd_addr_h_live;
	logic [EPI_FRAME_PTR_W-1:0] rd_addr_v_post;

	assign rd_addr_h_live = wr_addr_row_major;
	assign rd_addr_v_post = addr_row_major(v_epi_idx, v_spatial_idx);
	assign storage_rd_addr = vertical_output_active ? rd_addr_v_post : rd_addr_h_live;

	// ---------------------------------------------------------------------
	// Storage write decode
	// ---------------------------------------------------------------------
	integer bi;
	always_comb begin
		for (bi = 0; bi < 12; bi = bi + 1) begin
			storage_we[bi]      = 1'b0;
			storage_wr_addr[bi] = wr_addr_calc;
		end

		storage_we_8v      = 1'b0;
		storage_wr_addr_8v = wr_addr_transposed;
		storage_wr_data    = pixel_in;

		storage_wr_addr[4] = wr_addr_frame4;
		storage_wr_addr[8] = wr_addr_row_major;

		if (write_phase) begin
			case (capture_in_count)
				5'd0  : storage_we[0]  = 1'b1;
				5'd1  : storage_we[1]  = 1'b1;
				5'd2  : storage_we[2]  = 1'b1;
				5'd3  : storage_we[3]  = 1'b1;
				5'd4  : storage_we[4]  = 1'b1;
				5'd5  : storage_we[5]  = 1'b1;
				5'd6  : storage_we[6]  = 1'b1;
				5'd7  : storage_we[7]  = 1'b1;
				5'd8  : begin
					storage_we[8]  = 1'b1;
					storage_we_8v  = 1'b1;
				end
				5'd9  : storage_we[9]  = 1'b1;
				5'd10 : storage_we[10] = 1'b1;
				5'd11 : storage_we[11] = 1'b1;
				5'd13 : storage_we[9]  = 1'b1;
				5'd14 : storage_we[10] = 1'b1;
				5'd15 : storage_we[11] = 1'b1;
				default: begin
				end
			endcase
		end

		if (v08_store_phase) begin
			storage_we[4] = 1'b1;
		end
	end

	// ---------------------------------------------------------------------
	// Control
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : LF_Control_And_Addressing
		if (solf_in) begin
			in_lf_flag                  <= 1'b1;
			capture_in_count            <= 5'd0;
			row_in_count                <= '0;
			column_in_count             <= '0;
			shared_banks_5_to_8_released <= 1'b0;
		end
		else if (eolf_in) begin
			in_lf_flag       <= 1'b0;
			capture_in_count <= 5'd0;
			row_in_count     <= '0;
			column_in_count  <= '0;
		end

		if ((in_lf_flag || solf_in) && pixel_valid_in) begin
			h_read_phase_d    <= h_read_phase;
			pixel_in_d        <= pixel_in;
			row_in_count_d    <= row_in_count;
			column_in_count_d <= column_in_count;

			if (soc_in) begin
				row_in_count    <= '0;
				column_in_count <= {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
			end
			else begin
				if (column_in_count == IMAGE_DIM-1) begin
					column_in_count <= '0;
					row_in_count    <= row_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
				else begin
					column_in_count <= column_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
			end

			if (eoc_in) begin
				row_in_count    <= '0;
				column_in_count <= '0;

				if (!eolf_in && capture_in_count < 5'd16) begin
					if (capture_in_count == H_READ_CAPTURE) begin
						shared_banks_5_to_8_released <= 1'b1;
					end
					capture_in_count <= capture_in_count + 5'd1;
				end
			end
		end
		else begin
			h_read_phase_d <= 1'b0;
		end
	end

	// ---------------------------------------------------------------------
	// Vertical post-frame readout
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : Vertical_Post_Frame_Output
		v_read_issue_d <= 1'b0;

		if (solf_in) begin
			vertical_output_pending <= 1'b0;
			vertical_output_active  <= 1'b0;
			v_epi_idx               <= '0;
			v_spatial_idx           <= '0;
			v_epi_idx_d             <= '0;
			v_spatial_idx_d         <= '0;
		end
		else if (eolf_in) begin
			vertical_output_pending <= 1'b1;
		end
		else begin
			if (vertical_output_pending) begin
				vertical_output_pending <= 1'b0;
				vertical_output_active  <= 1'b1;
				v_epi_idx               <= '0;
				v_spatial_idx           <= '0;
			end
			else if (vertical_output_active) begin
				v_read_issue_d  <= 1'b1;
				v_epi_idx_d     <= v_epi_idx;
				v_spatial_idx_d <= v_spatial_idx;

				if (v_spatial_idx == IMAGE_DIM-1) begin
					v_spatial_idx <= '0;

					if (v_epi_idx == IMAGE_DIM-1) begin
						v_epi_idx              <= '0;
						vertical_output_active <= 1'b0;
					end
					else begin
						v_epi_idx <= v_epi_idx + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
					end
				end
				else begin
					v_spatial_idx <= v_spatial_idx + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
				end
			end
		end
	end

	// ---------------------------------------------------------------------
	// Output
	// ---------------------------------------------------------------------
	always_ff @(posedge clk) begin : EPI_Output
		epi_valid_out      <= 1'b0;
		epi_column_idx_out <= '0;
		epi_idx_out        <= '0;
		orientation_out    <= 1'b0;

		for (int c = 0; c < 9; c++) begin
			epi_column_out[c] <= 15'd0;
		end

		if (h_read_phase_d) begin
			orientation_out    <= 1'b0;
			epi_valid_out      <= 1'b1;
			epi_idx_out        <= row_in_count_d;
			epi_column_idx_out <= column_in_count_d;

			epi_column_out[0] <= storage_rd_data[4];
			epi_column_out[1] <= storage_rd_data[5];
			epi_column_out[2] <= storage_rd_data[6];
			epi_column_out[3] <= storage_rd_data[7];
			epi_column_out[4] <= storage_rd_data[8];
			epi_column_out[5] <= storage_rd_data[9];
			epi_column_out[6] <= storage_rd_data[10];
			epi_column_out[7] <= storage_rd_data[11];
			epi_column_out[8] <= pixel_in_d;
		end
		else if (v_read_issue_d) begin
			orientation_out    <= 1'b1;
			epi_valid_out      <= 1'b1;
			epi_idx_out        <= v_epi_idx_d;
			epi_column_idx_out <= v_spatial_idx_d;

			epi_column_out[0] <= storage_rd_data[0];
			epi_column_out[1] <= storage_rd_data[1];
			epi_column_out[2] <= storage_rd_data[2];
			epi_column_out[3] <= storage_rd_data[3];
			epi_column_out[4] <= storage_rd_data_8v;
			epi_column_out[5] <= storage_rd_data[9];
			epi_column_out[6] <= storage_rd_data[10];
			epi_column_out[7] <= storage_rd_data[11];
			epi_column_out[8] <= storage_rd_data[4];
		end
	end

endmodule