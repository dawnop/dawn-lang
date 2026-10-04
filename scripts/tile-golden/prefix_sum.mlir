cuda_tile.module @m {
  entry @prefix_sum(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [100], strides = [1] : tensor_view<100xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = scan %7 dim=0 reverse=false identities=[0.0 : f64] : tile<128xf64> -> tile<128xf64> (%10: tile<f64>, %11: tile<f64>) {
      %12 = addf %10, %11 rounding<nearest_even> : tile<f64>
      yield %12 : tile<f64>
    }
    %13 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [100], strides = [1] : tensor_view<100xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>
    %16 = store_view_tko weak %9, %15[%4] token=%8 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
