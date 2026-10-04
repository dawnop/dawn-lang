cuda_tile.module @m {
  entry @attn_softmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %14 = reduce %12 dim=0 identities=[-Infinity : f64] : tile<64xf64> -> tile<f64> (%15: tile<f64>, %16: tile<f64>) {
      %17 = maxf %15, %16 : tile<f64>
      yield %17 : tile<f64>
    }
    %18 = reshape %14 : tile<f64> -> tile<1xf64>
    %19 = broadcast %18 : tile<1xf64> -> tile<64xf64>
    %20 = subf %12, %19 rounding<nearest_even> : tile<64xf64>
    %21 = exp %20 : tile<64xf64>
    %22 = reduce %21 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%23: tile<f64>, %24: tile<f64>) {
      %25 = addf %23, %24 rounding<nearest_even> : tile<f64>
      yield %25 : tile<f64>
    }
    %26 = reshape %22 : tile<f64> -> tile<1xf64>
    %27 = broadcast %26 : tile<1xf64> -> tile<64xf64>
    %28 = divf %21, %27 rounding<nearest_even> : tile<64xf64>
    %29 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %31 = make_partition_view %30 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %32 = store_view_tko weak %28, %31[%9] token=%13 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
