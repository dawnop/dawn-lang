cuda_tile.module @m {
  entry @int_ops(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 1000> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <i32: 1> : tile<128xi32>
    %13 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %14 = broadcast %13 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %15 = offset %14, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %18 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %19 = broadcast %18 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %20 = offset %19, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %23 = ori %21, %12 : tile<128xi32>
    %24 = subi %16, %21 : tile<128xi32>
    %25 = mulhii %16, %21 : tile<128xi32>
    %26 = divi %16, %23 signed : tile<128xi32>
    %27 = remi %16, %23 signed : tile<128xi32>
    %28 = maxi %16, %21 signed : tile<128xi32>
    %29 = mini %16, %21 signed : tile<128xi32>
    %30 = negi %16 : tile<128xi32>
    %31 = absi %24 : tile<128xi32>
    %32 = constant <i32: 3> : tile<128xi32>
    %33 = shli %16, %32 : tile<128xi32>
    %34 = constant <i32: 5> : tile<128xi32>
    %35 = shri %16, %34 signed : tile<128xi32>
    %36 = constant <i32: 5> : tile<128xi32>
    %37 = shri %16, %36 unsigned : tile<128xi32>
    %38 = itof %16 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %39 = constant <f64: 0.5> : tile<128xf64>
    %40 = mulf %38, %39 rounding<nearest_even> : tile<128xf64>
    %41 = ftoi %40 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi32>
    %42 = trunci %16 : tile<128xi32> -> tile<128xi1>
    %43 = exti %42 unsigned : tile<128xi1> -> tile<128xi32>
    %44 = bitcast %16 : tile<128xi32> -> tile<128xf32>
    %45 = bitcast %44 : tile<128xf32> -> tile<128xi32>
    %46 = addi %24, %25 : tile<128xi32>
    %47 = xori %46, %26 : tile<128xi32>
    %48 = addi %47, %27 : tile<128xi32>
    %49 = xori %48, %28 : tile<128xi32>
    %50 = addi %49, %29 : tile<128xi32>
    %51 = xori %50, %30 : tile<128xi32>
    %52 = addi %51, %31 : tile<128xi32>
    %53 = xori %52, %33 : tile<128xi32>
    %54 = addi %53, %35 : tile<128xi32>
    %55 = xori %54, %37 : tile<128xi32>
    %56 = andi %16, %21 : tile<128xi32>
    %57 = addi %55, %56 : tile<128xi32>
    %58 = ori %16, %21 : tile<128xi32>
    %59 = xori %57, %58 : tile<128xi32>
    %60 = xori %16, %21 : tile<128xi32>
    %61 = addi %59, %60 : tile<128xi32>
    %62 = xori %61, %41 : tile<128xi32>
    %63 = addi %62, %43 : tile<128xi32>
    %64 = xori %63, %45 : tile<128xi32>
    %65 = reshape %arg2 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %66 = broadcast %65 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %67 = offset %66, %9 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %68 = store_ptr_tko weak %67, %64, %11 token=%22 : tile<128xptr<i32>>, tile<128xi32>, tile<128xi1> -> token
    return
  }
}
