cuda_tile.module @m {
  entry @ols_beta(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 8> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<8xi32>
    %4 = iota : tile<8xi32>
    %5 = constant <i32: 16> : tile<8xi32>
    %6 = muli %4, %5 : tile<8xi32>
    %7 = addi %3, %6 : tile<8xi32>
    %8 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %9 = broadcast %8 : tile<1xptr<f64>> -> tile<8xptr<f64>>
    %10 = offset %9, %7 : tile<8xptr<f64>>, tile<8xi32> -> tile<8xptr<f64>>
    %11, %12 = load_ptr_tko weak %10 token=%0 : tile<8xptr<f64>> -> tile<8xf64>, token
    %13 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [8], strides = [1] : tensor_view<8xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(8), padding_value = zero, tensor_view<8xf64, strides=[1]>, dim_map=[0]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19 = store_view_tko weak %11, %15[%16] token=%12 : tile<8xf64>, partition_view<tile=(8), padding_value = zero, tensor_view<8xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
