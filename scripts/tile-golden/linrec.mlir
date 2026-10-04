cuda_tile.module @m {
  entry @linrec(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %14, %15 = scan %7, %12 dim=0 reverse=false identities=[1.0 : f64, 0.0 : f64] : tile<64xf64>, tile<64xf64> -> tile<64xf64>, tile<64xf64> (%16: tile<f64>, %17: tile<f64>, %18: tile<f64>, %19: tile<f64>) {
      %20 = mulf %17, %16 rounding<nearest_even> : tile<f64>
      %21 = fma %17, %18, %19 rounding<nearest_even> : tile<f64>
      yield %20, %21 : tile<f64>, tile<f64>
    }
    %22 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %25 = store_view_tko weak %15, %24[%4] token=%13 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
