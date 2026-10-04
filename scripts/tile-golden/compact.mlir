cuda_tile.module @m {
  entry @compact(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [100], strides = [1] : tensor_view<100xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = constant <f64: 0.0> : tile<128xf64>
    %10 = cmpf greater_than ordered %7, %9 : tile<128xf64> -> tile<128xi1>
    %11 = constant <i32: 1> : tile<128xi32>
    %12 = constant <i32: 0> : tile<128xi32>
    %13 = select %10, %11, %12 : tile<128xi1>, tile<128xi32>
    %14 = scan %13 dim=0 reverse=false identities=[0 : i32] : tile<128xi32> -> tile<128xi32> (%15: tile<i32>, %16: tile<i32>) {
      %17 = addi %15, %16 : tile<i32>
      yield %17 : tile<i32>
    }
    %18 = subi %14, %13 : tile<128xi32>
    %19 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %18 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22 = store_ptr_tko weak %21, %7, %10 token=%8 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
