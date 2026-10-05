cuda_tile.module @m {
  entry @trig_sweep(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 500> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %18 = constant <f64: 1.0> : tile<128xf64>
    %19 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22, %23 = load_ptr_tko weak %21, %11, %18 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %24 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27, %28 = load_ptr_tko weak %26, %11, %18 token=%23 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %29 = sin %16 : tile<128xf64>
    %30 = reshape %29 : tile<128xf64> -> tile<1x128xf64>
    %31 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %32 = make_tensor_view %31, shape = [7, 500], strides = [500, 1] : tensor_view<7x500xf64, strides=[500, 1]>
    %33 = make_partition_view %32 : partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>
    %34, %35, %36 = get_tile_block_id : tile<i32>
    %37, %38, %39 = get_tile_block_id : tile<i32>
    %40 = constant <i32: 8> : tile<i32>
    %41 = muli %35, %40 : tile<i32>
    %42 = store_view_tko weak %30, %33[%41, %37] token=%28 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %43 = cos %16 : tile<128xf64>
    %44 = reshape %43 : tile<128xf64> -> tile<1x128xf64>
    %45 = constant <i32: 8> : tile<i32>
    %46 = muli %35, %45 : tile<i32>
    %47 = constant <i32: 1> : tile<i32>
    %48 = addi %46, %47 : tile<i32>
    %49 = store_view_tko weak %44, %33[%48, %37] token=%42 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %50 = tan %16 : tile<128xf64>
    %51 = reshape %50 : tile<128xf64> -> tile<1x128xf64>
    %52 = constant <i32: 8> : tile<i32>
    %53 = muli %35, %52 : tile<i32>
    %54 = constant <i32: 2> : tile<i32>
    %55 = addi %53, %54 : tile<i32>
    %56 = store_view_tko weak %51, %33[%55, %37] token=%49 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %57 = sinh %16 : tile<128xf64>
    %58 = reshape %57 : tile<128xf64> -> tile<1x128xf64>
    %59 = constant <i32: 8> : tile<i32>
    %60 = muli %35, %59 : tile<i32>
    %61 = constant <i32: 3> : tile<i32>
    %62 = addi %60, %61 : tile<i32>
    %63 = store_view_tko weak %58, %33[%62, %37] token=%56 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %64 = cosh %16 : tile<128xf64>
    %65 = reshape %64 : tile<128xf64> -> tile<1x128xf64>
    %66 = constant <i32: 8> : tile<i32>
    %67 = muli %35, %66 : tile<i32>
    %68 = constant <i32: 4> : tile<i32>
    %69 = addi %67, %68 : tile<i32>
    %70 = store_view_tko weak %65, %33[%69, %37] token=%63 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %71 = atan2 %16, %22 : tile<128xf64>
    %72 = reshape %71 : tile<128xf64> -> tile<1x128xf64>
    %73 = constant <i32: 8> : tile<i32>
    %74 = muli %35, %73 : tile<i32>
    %75 = constant <i32: 5> : tile<i32>
    %76 = addi %74, %75 : tile<i32>
    %77 = store_view_tko weak %72, %33[%76, %37] token=%70 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %78 = remf %16, %27 : tile<128xf64>
    %79 = reshape %78 : tile<128xf64> -> tile<1x128xf64>
    %80 = constant <i32: 8> : tile<i32>
    %81 = muli %35, %80 : tile<i32>
    %82 = constant <i32: 6> : tile<i32>
    %83 = addi %81, %82 : tile<i32>
    %84 = store_view_tko weak %79, %33[%83, %37] token=%77 : tile<1x128xf64>, partition_view<tile=(1x128), padding_value = zero, tensor_view<7x500xf64, strides=[500, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
