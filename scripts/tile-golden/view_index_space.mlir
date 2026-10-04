cuda_tile.module @m {
  entry @view_index_space(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 1> : tile<i32>
    %3 = constant <i32: 0> : tile<i32>
    %4 = offset %arg0, %3 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %5, %6 = load_ptr_tko weak %4 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %7 = constant <i32: 1> : tile<i32>
    %8 = offset %arg0, %7 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %9, %10 = load_ptr_tko weak %8 token=%6 : tile<ptr<i32>> -> tile<i32>, token
    %11 = constant <i32: 2> : tile<i32>
    %12 = offset %arg0, %11 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%10 : tile<ptr<i32>> -> tile<i32>, token
    %15 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [%5, %9], strides = [%9, %13] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %17 = make_partition_view %16 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>
    %18, %19 = get_index_space_shape %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %20, %21 = get_index_space_shape %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %22 = constant <f64: 0.0> : tile<16x16xf64>
    %23, %24 = for %25 in (%1 to %18, step %2) : tile<i32> iter_values(%26 = %22, %27 = %14) -> (tile<16x16xf64>, token) {
      %28, %29 = for %30 in (%1 to %21, step %2) : tile<i32> iter_values(%31 = %26, %32 = %27) -> (tile<16x16xf64>, token) {
        %33, %34 = load_view_tko weak %17[%25, %30] token=%32 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
        %35 = addf %31, %33 rounding<nearest_even> : tile<16x16xf64>
        continue %35, %34 : tile<16x16xf64>, token
      }
      continue %28, %29 : tile<16x16xf64>, token
    }
    %36 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %37 = make_tensor_view %36, shape = [16, 16], strides = [16, 1] : tensor_view<16x16xf64, strides=[16, 1]>
    %38 = make_partition_view %37 : partition_view<tile=(16x16), padding_value = zero, tensor_view<16x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %39, %40, %41 = get_tile_block_id : tile<i32>
    %42, %43, %44 = get_tile_block_id : tile<i32>
    %45 = store_view_tko weak %23, %38[%39, %43] token=%24 : tile<16x16xf64>, partition_view<tile=(16x16), padding_value = zero, tensor_view<16x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %46 = reshape %18 : tile<i32> -> tile<1xi32>
    %47 = broadcast %46 : tile<1xi32> -> tile<1xi32>
    %48 = assume div_by<16>, %arg3 : tile<ptr<i32>>
    %49 = make_tensor_view %48, shape = [2], strides = [1] : tensor_view<2xi32, strides=[1]>
    %50 = make_partition_view %49 : partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>
    %51 = constant <i32: 2> : tile<i32>
    %52 = muli %39, %51 : tile<i32>
    %53 = store_view_tko weak %47, %50[%52] token=%45 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %54 = reshape %21 : tile<i32> -> tile<1xi32>
    %55 = broadcast %54 : tile<1xi32> -> tile<1xi32>
    %56 = constant <i32: 2> : tile<i32>
    %57 = muli %39, %56 : tile<i32>
    %58 = constant <i32: 1> : tile<i32>
    %59 = addi %57, %58 : tile<i32>
    %60 = store_view_tko weak %55, %50[%59] token=%53 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
